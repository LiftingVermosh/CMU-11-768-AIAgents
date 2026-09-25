"""Create human labels, validate them, and score validator predictions."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from validator.prediction import (
    ERROR_FAMILIES,
    TERMINAL_FAMILY,
    Error,
    PredictionFile,
)

RELEASE = Path(__file__).resolve().parents[1]


class HumanLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    errors: list[Error] | None = None

    @model_validator(mode="after")
    def valid_errors(self) -> "HumanLabel":
        if self.errors is None:
            return self
        families = [error.family.value for error in self.errors]
        if len(families) != len(set(families)):
            raise ValueError("an error family may appear at most once per run")
        if TERMINAL_FAMILY in families and len(families) > 1:
            raise ValueError("execution_failure must be the only error for its run")
        return self


class LabelFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labels: list[HumanLabel] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_runs(self) -> "LabelFile":
        run_ids = [label.run_id for label in self.labels]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("run_id values must be unique")
        return self


@dataclass(frozen=True)
class Label:
    run_id: str
    values: dict[str, bool | None]
    evidence: dict[str, str]


def _artifact_ids(artifacts: Path) -> set[str]:
    return {path.parent.name for path in artifacts.glob("*/result.json")}


def load_labels(path: Path, artifacts: Path | None = None) -> list[Label]:
    document = LabelFile.model_validate_json(path.read_text())
    labels: list[Label] = []
    for item in document.labels:
        if item.errors is None:
            raise ValueError(f"{path}: run {item.run_id!r} has not been reviewed")
        errors = {error.family.value: error.evidence for error in item.errors}
        terminal = TERMINAL_FAMILY in errors
        values = {
            family: None if terminal and family != TERMINAL_FAMILY else family in errors
            for family in ERROR_FAMILIES
        }
        labels.append(Label(item.run_id, values, errors))

    if artifacts is not None:
        expected = _artifact_ids(artifacts)
        seen = {label.run_id for label in labels}
        missing, extra = expected - seen, seen - expected
        if missing or extra:
            raise ValueError(
                f"labels/artifacts mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
            )
    return labels


def initialize_labels(path: Path, artifacts: Path, *, overwrite: bool = False) -> int:
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} exists; pass --overwrite to replace it")
    run_ids = sorted(_artifact_ids(artifacts))
    if not run_ids:
        raise ValueError(f"no result.json artifacts found below {artifacts}")
    path.parent.mkdir(parents=True, exist_ok=True)
    document = LabelFile(labels=[HumanLabel(run_id=run_id) for run_id in run_ids])
    path.write_text(document.model_dump_json(indent=2) + "\n")
    return len(run_ids)


def score(
    labels_path: Path, predictions_path: Path
) -> dict[str, dict[str, int | float | bool] | float]:
    labels = load_labels(labels_path)
    predictions_file = PredictionFile.model_validate_json(predictions_path.read_text())
    predictions = {}
    for prediction in predictions_file.predictions:
        if prediction.run_id in predictions:
            raise ValueError(f"duplicate prediction for run_id {prediction.run_id!r}")
        families = [error.family.value for error in prediction.errors]
        if len(families) != len(set(families)):
            raise ValueError(f"duplicate error family for run_id {prediction.run_id!r}")
        predictions[prediction.run_id] = set(families)

    label_ids = {label.run_id for label in labels}
    prediction_ids = set(predictions)
    if label_ids != prediction_ids:
        raise ValueError(
            f"labels/predictions mismatch; missing={sorted(label_ids - prediction_ids)}, "
            f"extra={sorted(prediction_ids - label_ids)}"
        )

    report: dict[str, dict[str, int | float | bool] | float] = {}
    mcc_values = []
    for family in ERROR_FAMILIES:
        tp = tn = fp = fn = 0
        for label in labels:
            truth = label.values[family]
            if truth is None:
                continue
            predicted = family in predictions[label.run_id]
            tp += int(truth and predicted)
            tn += int(not truth and not predicted)
            fp += int(not truth and predicted)
            fn += int(truth and not predicted)
        positive_support = tp + fn
        negative_support = tn + fp
        insufficient_support = positive_support == 0 or negative_support == 0
        denominator = math.sqrt(
            (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
        )
        # A zero denominator includes constant predictions on mixed truth. MCC is
        # defined as zero for that case and by convention for insufficient truth
        # support; the flag below distinguishes the latter.
        mcc = 0.0 if denominator == 0 else (tp * tn - fp * fn) / denominator
        report[family] = {
            "tp": tp,
            "tn": tn,
            "fp": fp,
            "fn": fn,
            "positive_support": positive_support,
            "negative_support": negative_support,
            "insufficient_support": insufficient_support,
            "mcc": mcc,
        }
        mcc_values.append(mcc)
    report["macro_mcc"] = sum(mcc_values) / len(ERROR_FAMILIES)
    return report


def init_labels_main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Create a blank label entry per run.")
    parser.add_argument("--labels", type=Path, default=RELEASE / "labels.json")
    parser.add_argument("--artifacts", type=Path, default=RELEASE / "runs")
    parser.add_argument("--overwrite", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        count = initialize_labels(
            arguments.labels, arguments.artifacts, overwrite=arguments.overwrite
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"wrote {count} blank label entry(s) to {arguments.labels}")


def validate_labels_main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Validate labels and artifact coverage.")
    parser.add_argument("--labels", type=Path, default=RELEASE / "labels.json")
    parser.add_argument("--artifacts", type=Path, default=RELEASE / "runs")
    arguments = parser.parse_args(argv)
    try:
        labels = load_labels(arguments.labels, arguments.artifacts)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"valid: {len(labels)} human-reviewed label(s)")


def score_main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Score predictions against human labels.")
    parser.add_argument("--labels", type=Path, default=RELEASE / "labels.json")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    arguments = parser.parse_args(argv)
    try:
        report = score(arguments.labels, arguments.predictions)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if arguments.json:
        print(json.dumps(report, indent=2))
        return
    for family in ERROR_FAMILIES:
        row = report[family]
        assert isinstance(row, dict)
        print(
            f"{family:20} MCC={row['mcc']:.4f}  "
            f"TP={row['tp']} TN={row['tn']} FP={row['fp']} FN={row['fn']}  "
            f"support(+/-)={row['positive_support']}/{row['negative_support']}"
        )
        if row["insufficient_support"]:
            print(
                f"{'':20} WARNING: insufficient ground-truth support; "
                "MCC reported as 0 by convention"
            )
    print(f"{'macro_mcc':20} {report['macro_mcc']:.4f}")
