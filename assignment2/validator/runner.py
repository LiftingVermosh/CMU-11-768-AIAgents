"""Ask a validator about every run and write down what it said.

    python -m validator.runner [--solution MODULE] [--artifacts DIR] [--out PATH]

`--solution` names the module holding `validate(run)` and `--artifacts` the runs
to judge, so one submission can be graded on runs it was never given.

A run whose validator raises is retried after the sweep, with a pause between
rounds. Runs that still fail are left out of the output file and the runner
exits with an error naming them; `--resume` then judges only the runs missing
from an existing output file. A `validate()` return value that violates
`prediction.py` is a contract error, not a transient failure, and stops the
runner immediately.
"""

import argparse
import importlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from validator.prediction import Prediction, PredictionFile

RELEASE = Path(__file__).resolve().parents[1]
ARTIFACTS = RELEASE / "artifacts"
RETRY_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 30.0


@dataclass(frozen=True)
class Run:
    run_id: str
    task_id: str
    instructions: str
    messages: list[dict]
    figure: Path | None
    #: Keyed by the name the instructions call the file.
    inputs: dict[str, Path]

    @classmethod
    def load(cls, directory: Path, artifact_root: Path) -> "Run":
        record = json.loads((directory / "result.json").read_text())
        figure = directory / "figure.png"
        inputs = {
            item["name"]: artifact_root / item["path"]
            for item in record["task"].get("inputs") or []
        }
        missing_inputs = [str(path) for path in inputs.values() if not path.is_file()]
        if missing_inputs:
            raise FileNotFoundError(
                f"{directory / 'result.json'}: recorded input files do not exist: "
                f"{missing_inputs}"
            )
        return cls(
            run_id=record["run_id"],
            task_id=record["task_id"],
            instructions=record["task"]["instructions"],
            messages=record["trajectory"]["messages"],
            figure=figure if figure.exists() else None,
            inputs=inputs,
        )


def runs(artifacts: Path = ARTIFACTS, artifact_root: Path = RELEASE) -> list[Run]:
    return [
        Run.load(path.parent, artifact_root)
        for path in sorted(artifacts.glob("*/result.json"))
    ]


def write_predictions(path: Path, predictions: dict[str, Prediction]) -> None:
    """Checkpoint the predictions collected so far, in run order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = [predictions[run_id] for run_id in sorted(predictions)]
    path.write_text(PredictionFile(predictions=ordered).model_dump_json(indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solution", default="validator.solution",
                        help="module exposing validate(run) -> list[Error]")
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS,
                        help="the runs to judge")
    parser.add_argument("--artifact-root", type=Path, default=RELEASE,
                        help="base directory for input paths recorded in each run")
    parser.add_argument("--out", type=Path, default=RELEASE / "output" / "predictions.json")
    parser.add_argument("--resume", action="store_true",
                        help="keep predictions already in --out and judge only the missing runs")
    arguments = parser.parse_args()

    validate = importlib.import_module(arguments.solution).validate
    predictions: dict[str, Prediction] = {}
    if arguments.resume and arguments.out.exists():
        existing = PredictionFile.model_validate_json(arguments.out.read_text())
        predictions = {item.run_id: item for item in existing.predictions}
        print(f"resuming: {len(predictions)} predictions already in {arguments.out}")
    pending = [run for run in runs(arguments.artifacts, arguments.artifact_root)
               if run.run_id not in predictions]
    failures: dict[str, str] = {}

    for attempt in range(RETRY_ATTEMPTS + 1):
        if not pending:
            break
        if attempt:
            delay = RETRY_DELAY_SECONDS * 2 ** (attempt - 1)
            print(f"retry {attempt}/{RETRY_ATTEMPTS}: {len(pending)} failed run(s), "
                  f"waiting {delay:.0f}s")
            time.sleep(delay)
        stage = f"retry {attempt}" if attempt else "validating"
        progress = tqdm(pending, unit="run")
        pending = []
        for run in progress:
            progress.set_description(f"{stage} {run.run_id}", refresh=True)
            try:
                errors = validate(run)
            except Exception as error:
                failures[run.run_id] = f"{type(error).__name__}: {error}"
                print(f"ERROR {run.run_id}: {failures[run.run_id]}")
                pending.append(run)
                continue
            predictions[run.run_id] = Prediction(run_id=run.run_id, errors=errors)
            families = [error.family.value for error in errors]
            print(f"  {run.run_id}: {families or 'acceptable'}")
            write_predictions(arguments.out, predictions)

    # Also create an output file when the artifact directory contains no runs.
    if not predictions:
        write_predictions(arguments.out, predictions)
    print(f"wrote {len(predictions)} predictions to {arguments.out}")
    if pending:
        details = "\n".join(f"  {run.run_id}: {failures[run.run_id]}" for run in pending)
        raise SystemExit(
            f"{len(pending)} run(s) failed after {RETRY_ATTEMPTS} retries and were not "
            f"written to {arguments.out}:\n{details}\n"
            "Check the endpoint URL and token in .env and that the validator model is "
            "deployed (uv run modal app list), then rerun with --resume to judge only "
            "the missing runs."
        )


if __name__ == "__main__":
    main()
