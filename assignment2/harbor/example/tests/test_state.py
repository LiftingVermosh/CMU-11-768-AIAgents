"""Verifier for the worked example: does the delivered bar chart say the right thing?

===============================================================================
READ THIS FIRST -- YOU ARE NOT REQUIRED TO WRITE ANYTHING THIS STRONG.
===============================================================================
This file is a staff demonstration of how far a verifier *can* be pushed. It is
deliberately over-built. Writing it took far longer than the 10-25 minutes the
assignment budgets for packaging one task, and reproducing it is explicitly NOT
part of your grade.

What the assignment actually asks of you:

  1. Package the task as a harbor environment that FAILS CLOSED -- an empty or
     unimplemented solution must score 0. (The scaffold `harbor init` generates
     does the opposite: it scores 1.0 on a no-op. That is the trap.)
  2. Write the best verifier you can reasonably manage. "The file exists, it is
     a valid non-blank PNG, and the script that made it re-runs" is an
     acceptable verifier. Section S1 below, on its own, is already that.
  3. Across your packaged tasks, write TWO plausible-but-wrong mutant solutions
     and report both rewards. Your verifier must reject one with reward 0 and
     accept the other with reward 1.0. For the rejected mutant, name the
     assertion that caught it. For the accepted mutant, explain what the
     verifier cannot detect; that measured gap is the point of the report
     question.

So: read this file to see what the ceiling looks like and to steal ideas, not
to match it. The five strategies are laid out in ascending order of cost, and
each section says what it buys and what it costs. Most of you should stop
after S1, maybe S2.

===============================================================================
WHERE THIS CODE RUNS
===============================================================================
harbor's default verifier mode is SHARED. After the agent phase ends, harbor
copies tests/ into the agent's own container and runs tests/test.sh there as
root. That means:

  /app      the agent's workspace, exactly as the agent left it -- so plot.py
            survives, not just figure.png. This whole file depends on that.
  /tests    this directory. It is copied in AFTER the agent phase ends, so the
            AGENT never got to see or edit these assertions -- but at verify
            time it is an ordinary writable directory, and so is /app. That
            matters below. The re-run deliberately does NOT get /tests on its
            import path, but a determined script running as root could still
            open this file by absolute path, and could walk /tmp looking for
            whatever the verifier squirrelled away -- so nothing that sits on
            disk is trusted on its own. The delivered artifacts are copied
            aside before the first re-run AND digested, with the digests held
            in this process's memory, which is the one place the re-run cannot
            reach.
  /logs     /logs/agent, /logs/verifier, /logs/artifacts.

Writing "1" or "0" into /logs/verifier/reward.txt is what actually sets the
reward. tests/test.sh does that from pytest's exit status. Nothing here returns
a score directly.

===============================================================================
WHY NOT JUST LOOK AT THE PICTURE?
===============================================================================
Because a PNG is nearly opaque to a test. Pixels carry no scale, no tick text
and no series identity; deciding "is that bar 558 or 563 kilos tall" from
RGB values means writing an OCR pipeline and a chart parser, and getting both
right. So this verifier does not read the picture. It reads the PROGRAM THAT
MADE the picture, by re-executing it with matplotlib instrumented.

===============================================================================
THE FIVE STRATEGIES, AND WHICH MUTANT EACH ONE IS THE ONLY DEFENSE AGAINST
===============================================================================
  S1  cheap checks on the delivered artifact
      exists / valid non-blank PNG / input CSV untouched / script left behind
      cost: minutes.       catches: total failure -- no figure, an empty or
      truncated one, a blank canvas, or an agent that edited the input.

  S2  re-execute /app/plot.py in a scrubbed copy of the workspace with
      Figure.savefig hooked, and assert against the JSON manifest of the
      resulting artist tree (bar heights, tick labels, ylim, orientation)
      cost: the bulk of this file.  catches: mutants/sum_crates, and every
      other wrong-aggregation, wrong-order or missing-label error.

  S3  anti-forgery by digest: the savefig hook hashes the bytes it writes, and
      the delivered figure.png must be that image
      cost: ~25 lines.     ONLY defense against mutants/forgery -- an honest
      script on disk paired with a figure drawn from different data -- and
      against a script that saves the right chart and then moves a different
      PNG over the top of it, which no pixel comparison can see.

  S4  input-perturbation probe: re-execute a second time against a MODIFIED
      harvest_log.csv and require the plotted numbers to move
      cost: ~15 lines.     ONLY defense against mutants/hardcoded -- correct
      totals typed in by hand, CSV never opened. Note that S2 and S3 both
      pass that mutant cleanly. This is the single highest-value idea here.

  S5  cross-check the agent's own declared numbers (plotted_values.json)
      against both the answer key and what was actually drawn
      cost: ~10 lines.     catches self-inconsistency: a sidecar that agrees
      with the key but disagrees with the chart, or vice versa.

===============================================================================
ONE MORE DESIGN NOTE
===============================================================================
The expected totals are typed out by hand below rather than recomputed from
harvest_log.csv by this file. That is on purpose: a verifier that re-implements the
aggregation it is grading will happily pass a solution that repeats the
verifier's own bug. Answer keys should be independent of the thing they judge.
"""

import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

APP = Path("/app")  # the agent's workspace, post-agent-phase
FIGURE = APP / "figure.png"
SIDECAR = APP / "plotted_values.json"
CSV = APP / "harvest_log.csv"
SCRIPT_NAME = "plot.py"
TESTS = Path(__file__).resolve().parent
MANIFEST_NAME = FIGURE.stem + ".manifest.json"  # what the hook names figure.png's manifest
# Per re-execution, not per verifier run. The task's [verifier] timeout_sec is
# 600 and this file re-executes twice: at 300 each, a slow script would blow
# harbor's own budget and surface as VerifierTimeoutError a quarter of an hour
# later instead of as a clean 0. Keep 2 * this comfortably under that budget.
REEXEC_TIMEOUT = 120
# Call the image interpreter by absolute path. A uvx- or venv-based test.sh
# would hand you an ephemeral interpreter with NO matplotlib, and every
# re-execution below would die on the import.
PYTHON = "/usr/local/bin/python3"

# --- answer key (hand-derived; see the design note above) --------------------
# cleared rows only, yield = crates * kilos_per_crate, summed per orchard.
ORCHARDS = ["Brambleholt", "Cinderpeak", "Mistfen", "Willowdrift"]  # alphabetical, as the task demands
EXPECTED = [558.0, 420.0, 1230.0, 816.0]
# Near-miss answers this must reject, from the task's own design notes:
#   forgot the `cleared` filter -> 684, 525, 1500, 996
#   summed crates instead of kg ->  31,  56,   41,  68   (mutants/sum_crates)
CSV_SHA256 = "1cc30e44122bfccab866600d162712bf37471b835d05c4419c4af0f45a880615"

# S4's perturbation: one extra cleared Cinderpeak haul of 8 crates at 7.50 kg,
# so Cinderpeak must move 420 -> 480 and the other three orchards must not move
# at all. Chosen to be small, to touch exactly one group, and to be un-guessable
# from the original file -- a hard-coded script cannot follow it.
EXTRA_ROW = "521,Cinderpeak,dawn,8,7.50,cleared\n"
PERTURBED = [558.0, 480.0, 1230.0, 816.0]

# S3 and S5 grade what the agent HANDED IN, so both need a copy taken before
# any re-run can overwrite it: /app is writable at verify time, and a script
# that saves to "/app/figure.png" by absolute path rewrites its own deliverables
# every time the verifier re-executes it -- with S4's perturbed numbers, at
# that. The copy goes to an unguessable path rather than a fixed /tmp one, and
# its digest is recorded in _DELIVERED_SHA at copy time. The path alone is not
# enough: the re-run is root and can glob /tmp for "figure.png" and overwrite
# whatever it finds -- measured, and it scored 1.0 before the digest existed.
# The digest lives in this process's memory, so laundering the copy no longer
# helps.
DELIVERED_DIR = Path(tempfile.mkdtemp(prefix="delivered_"))
DELIVERED_BACKUP = DELIVERED_DIR / "figure.png"
DELIVERED_SIDECAR = DELIVERED_DIR / "plotted_values.json"
_DELIVERED_SHA: dict[Path, str] = {}

_HOOK_DIR: Path | None = None
_SNAPSHOT_TAKEN = False


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_delivered() -> None:
    """Copy the agent's deliverables out of reach of the re-runs. Idempotent."""
    global _SNAPSHOT_TAKEN
    if _SNAPSHOT_TAKEN:
        return
    for source, destination in ((FIGURE, DELIVERED_BACKUP), (SIDECAR, DELIVERED_SIDECAR)):
        if source.exists():
            shutil.copy2(source, destination)
            _DELIVERED_SHA[destination] = _sha256(destination)
    _SNAPSHOT_TAKEN = True


def _unlaundered(path: Path) -> Path:
    """The snapshot, re-checked against the digest taken before any re-run."""
    assert _sha256(path) == _DELIVERED_SHA.get(path), (
        f"the copy of {path.name} taken before the first re-run was overwritten "
        "while the script under test was running; the delivered artifact is "
        "graded against a digest recorded before that could happen"
    )
    return path


def _instrumentation_dir() -> Path:
    """A private copy of the savefig hook, for the re-run's PYTHONPATH.

    The re-run needs `sitecustomize.py` importable. Pointing PYTHONPATH at
    /tests would do that -- and would also hand the script being graded this
    file, EXPECTED and all, at exactly the moment it is being graded. Copy out
    only the two instrumentation modules instead.
    """
    global _HOOK_DIR
    if _HOOK_DIR is None:
        private = Path(tempfile.mkdtemp(prefix="hook_"))
        for name in ("figure_manifest.py", "sitecustomize.py"):
            shutil.copy2(TESTS / name, private / name)
        _HOOK_DIR = private
    return _HOOK_DIR


# ============================================================== shared helpers
def _find_script() -> Path:
    """The script the instructions asked for, or any /app script that saves a figure.

    The fallback is deliberate leniency: the instructions name plot.py, but an
    agent that solved the task in `make_chart.py` has not actually failed the
    task. Be strict about the answer, forgiving about the filename.
    """
    named = APP / SCRIPT_NAME
    if named.exists():
        return named
    fallback = sorted(
        path
        for path in APP.rglob("*.py")
        if path.is_file() and "savefig" in path.read_text(errors="replace")
    )
    assert fallback, (
        f"no {SCRIPT_NAME} in /app and no other .py file there calls savefig; "
        "the task requires a re-runnable plotting script"
    )
    return fallback[0]


def _fresh_manifests(root: Path, started: float) -> list[Path]:
    """Manifests under `root` written by the run that began at `started`."""
    return [
        path
        for path in sorted(root.rglob("*.manifest.json"))
        if path.stat().st_mtime >= started
    ]


def _reexecute(workdir: Path, csv_text: str | None = None) -> dict:
    """Run the agent's script in a throw-away copy of /app and return its manifest.

    This is the engine under S2, S3 and S4. Four details matter:

    1. It runs in a COPY of /app, never in /app itself. Every PNG and manifest
       is deleted from the copy first, so nothing the agent handed in can be
       mistaken for something this run produced. Without the scrub, a script
       that writes nothing at all would "pass" by leaving the agent's own
       figure.png sitting there.
    2. PYTHONPATH points at a PRIVATE copy of sitecustomize.py, not at /tests.
       CPython imports a module named `sitecustomize` automatically at
       interpreter start-up, before any user code, and that module patches
       Figure.savefig to dump a JSON description of the artist tree next to
       every image saved. The agent's script is not modified and does not know.
       It must not be given /tests itself: this file is readable at verify time
       and contains the answer key.
    3. SOURCE_DATE_EPOCH pins the PNG's embedded timestamp, and the Dockerfile
       pre-builds the font cache, so the same figure renders byte-identically
       twice. S3 depends on that reproducibility.
    4. The instructions tell the agent that plot.py must use paths relative to
       its working directory. A correct solution that ignores that and writes
       /app/figure.png anyway is still a correct solution, so manifests are
       looked for under /app as well as under the copy.

    Pass csv_text to rewrite harvest_log.csv in the copy -- that is S4's probe.
    """
    script = _find_script()
    relative = script.relative_to(APP)
    if workdir.exists():
        shutil.rmtree(workdir)
    shutil.copytree(APP, workdir)
    for stale in (*workdir.rglob("*.png"), *workdir.rglob("*.manifest.json")):
        stale.unlink()
    if csv_text is not None:
        (workdir / CSV.name).write_text(csv_text)

    env = dict(
        os.environ,
        PYTHONPATH=str(_instrumentation_dir()),  # see (2) above
        MPLBACKEND="Agg",             # headless; there is no display in here
        HOME="/tmp",                  # matplotlib needs a writable config dir
        SOURCE_DATE_EPOCH="1700000000",  # see (3) above
        # No __pycache__ directories: everything this run writes into the copy
        # is evidence, and bytecode caches are not evidence.
        PYTHONDONTWRITEBYTECODE="1",
    )
    # Timestamp floor for "was this file written by THIS run". One second of
    # slack absorbs coarse filesystem mtime granularity.
    started = time.time() - 1
    logs = Path(tempfile.mkdtemp(prefix="reexec_log_"))
    out_path, err_path = logs / "stdout.txt", logs / "stderr.txt"
    # Explicit files rather than capture_output: capture_output reads the pipes
    # until EOF, and any background process the agent's script leaves running
    # inherits those pipes and holds them open: one stray sleeper turned a 15s
    # end-to-end run into a 255s one, measured. start_new_session puts the
    # re-run in its own process group, so a timeout can kill its children too.
    with out_path.open("wb") as out, err_path.open("wb") as err:
        proc = subprocess.Popen(
            [PYTHON, str(relative)],
            cwd=workdir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            start_new_session=True,
        )
        try:
            returncode = proc.wait(timeout=REEXEC_TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):  # pragma: no cover
                proc.kill()
            proc.wait()
            # Fail as a plain assertion. Letting TimeoutExpired escape, or
            # sitting here until harbor's own [verifier] timeout fires, turns a
            # slow solution into an infrastructure error instead of a 0.
            raise AssertionError(
                f"re-running {relative} did not finish within {REEXEC_TIMEOUT}s and was "
                "killed. The task requires a script that runs unattended, and the "
                "verifier re-executes it more than once.\n"
                f"stderr tail:\n{err_path.read_text(errors='replace')[-2000:]}"
            ) from None
    stderr = err_path.read_text(errors="replace")
    assert returncode == 0, (
        f"re-running {relative} failed with exit {returncode}. "
        f"The task requires a script that runs unattended.\n"
        f"stderr tail:\n{stderr[-2000:]}"
    )
    # Manifests this run produced, in the copy and -- for a script that saves by
    # absolute path -- in /app. Without the second list, a correct solution that
    # calls fig.savefig("/app/figure.png") is failed for never calling savefig.
    candidates = _fresh_manifests(workdir, started) + _fresh_manifests(APP, started)
    # No manifest anywhere means no matplotlib figure was saved where the
    # verifier can see it: a PNG drawn by hand (PIL rectangles, or copied in
    # from elsewhere) leaves no artist tree to inspect, and neither does a
    # script that saves outside both directories.
    assert candidates, (
        f"{relative} ran but no matplotlib figure was saved where the verifier can see "
        "it: no manifest appeared beside any image, either in the re-run's working "
        "directory or in /app. Either Figure.savefig was never called (a hand-drawn or "
        "copied-in PNG does not count), or the figure was saved somewhere else entirely. "
        "plot.py must save its figure relative to its working directory."
    )
    # Grade the manifest for the figure the task asks for. Sorting and taking
    # the first would grade whatever image sorts earliest -- a correct script
    # that also saves an exploratory check_scatter.png would be graded on the
    # scatter.
    chosen = next((path for path in candidates if path.name == MANIFEST_NAME), candidates[0])
    manifest = json.loads(chosen.read_text())
    # The hook records the path it was handed; resolve it against the re-run's
    # working directory so a relative save and an absolute one both land right.
    # (Falling back to the manifest's own name recovers the image for a manifest
    # written before `saved_to` existed.)
    saved_to = manifest.get("saved_to")
    if saved_to:
        produced = Path(workdir, saved_to)
    else:
        produced = chosen.with_name(chosen.name.replace(".manifest.json", ".png"))
    manifest["_png"] = str(produced)
    return manifest


# --- small readers over the manifest JSON ------------------------------------
# The manifest schema is flat and JSON-native on purpose: you can assert
# against it without importing matplotlib. See tests/figure_manifest.py.
def _axes(manifest: dict, index: int = 0) -> dict:
    entries = manifest.get("axes") or []
    assert len(entries) > index, f"the figure has {len(entries)} axes, expected at least {index + 1}"
    return entries[index]


def _bar_values(manifest: dict) -> list[float]:
    """Bar heights, read off the BarContainer rather than off raw rectangles.

    Filter on type instead of indexing containers[0]: ax.bar(..., yerr=...)
    yields [ErrorbarContainer, BarContainer], with the error bars FIRST.
    """
    axes = _axes(manifest)
    bars = [c for c in axes.get("containers", []) if c.get("type") == "bar"]
    assert bars, (
        "axes 0 contains no bar container; the task asks for a bar chart "
        f"(containers present: {[c.get('type') for c in axes.get('containers', [])]})"
    )
    return [float(v) for container in bars for v in container["values"]]


def _ordered_orchards(manifest: dict) -> list[str]:
    """The orchard names as they appear along the x axis, left to right."""
    axes = _axes(manifest)
    labels = [str(t) for t in axes.get("xticklabels", []) if str(t).strip()]
    return [t for t in labels if t in ORCHARDS]


# --- fixtures: each does one re-run, shared across the tests that need it ----
@pytest.fixture(scope="session")
def manifest():
    """S2/S3/S5: re-run the agent's script against the ORIGINAL harvest_log.csv."""
    _snapshot_delivered()  # capture before anything can clobber it
    return _reexecute(Path("/tmp/reexec_asis"))


@pytest.fixture(scope="session")
def perturbed_manifest():
    """S4: re-run the agent's script against a MODIFIED harvest_log.csv.

    The perturbed bytes go into /app as well as into the throw-away copy. A
    correct solution is allowed to open "/app/harvest_log.csv" by absolute path, and
    perturbing only the copy would fail it for a bug it does not have.

    /app is writable at verify time, so this has to put the original back --
    in a finally, with the sha256 re-checked, because an exception between the
    write and the restore would leave a doctored input in place for whatever
    runs next.
    """
    _snapshot_delivered()
    original = CSV.read_bytes()
    assert hashlib.sha256(original).hexdigest() == CSV_SHA256, (
        "harvest_log.csv was already modified before the perturbation probe"
    )
    text = original.decode()
    if not text.endswith("\n"):
        text += "\n"
    perturbed = text + EXTRA_ROW
    try:
        CSV.write_text(perturbed)
        return _reexecute(Path("/tmp/reexec_perturbed"), csv_text=perturbed)
    finally:
        CSV.write_bytes(original)
        restored = hashlib.sha256(CSV.read_bytes()).hexdigest()
        assert restored == CSV_SHA256, (
            f"the perturbation probe failed to restore /app/harvest_log.csv (sha256 {restored}, "
            f"expected {CSV_SHA256}); the remaining checks would grade doctored input"
        )


# =============================================================================
# S1 -- CHEAP CHECKS ON THE DELIVERED ARTIFACT
#
# Everything here is a stat() or a PIL open. No re-execution, no matplotlib
# introspection. THIS SECTION ALONE IS AN ACCEPTABLE STUDENT VERIFIER: it fails
# closed on the empty solution, on a crashed run, on a zero-byte or blank PNG,
# and on an agent that "solved" the task by editing the input data. What it
# cannot do is tell a right chart from a wrong one -- every mutant in
# mutants/ sails straight through S1.
# =============================================================================
def test_s1_figure_exists():
    assert FIGURE.exists(), "no figure at /app/figure.png"


def test_s1_figure_is_a_valid_nonblank_png():
    import numpy as np
    from PIL import Image

    assert FIGURE.stat().st_size > 1000, f"figure.png is only {FIGURE.stat().st_size} bytes"
    with Image.open(FIGURE) as image:
        image.verify()  # PIL only checks structural integrity here...
    with Image.open(FIGURE) as image:  # ...and verify() closes the file, so reopen
        assert image.format == "PNG", f"figure.png is a {image.format}, not a PNG"
        assert min(image.size) > 100, f"figure.png is {image.size}"
        pixels = np.asarray(image.convert("RGB")).reshape(-1, 3)
    # A solid white canvas is a valid PNG. Four distinct colours is a low bar
    # that a real chart clears easily and an empty axes does not.
    assert len(np.unique(pixels, axis=0)) > 4, "figure.png is a flat colour field"


def test_s1_input_csv_was_not_modified():
    """Anti-cheat: doctoring the input would let a wrong aggregation land on the key.

    Cheap, and worth having in every data task you package. Without it, "make
    the test pass" has a shortcut that has nothing to do with the task.
    """
    assert CSV.exists(), "harvest_log.csv is missing from /app"
    digest = hashlib.sha256(CSV.read_bytes()).hexdigest()
    assert digest == CSV_SHA256, (
        f"harvest_log.csv was modified (sha256 {digest}, expected {CSV_SHA256}); "
        "the instructions forbid editing the input"
    )


def test_s1_plotting_script_was_left_behind():
    script = _find_script()
    assert script.stat().st_size > 0, f"{script} is empty"


# =============================================================================
# S2 -- CHART CONTENT, BY RE-EXECUTION UNDER A SAVEFIG HOOK
#
# The step from S1 to S2 is the expensive one, and it is where a verifier stops
# checking that a file exists and starts checking that an ANSWER is right.
# Every assertion below reads the manifest -- the JSON dump of the figure's
# artist tree -- so the checks are exact rather than inferred from pixels.
#
# Each test targets one clause of the instructions. Keep that mapping tight:
# an assertion the instructions did not ask for is a trap, not a test.
# =============================================================================
def test_s2_exactly_one_data_axes(manifest):
    # n_axes counts MAIN axes only: colorbars are in fig.axes but are not data
    # axes, and inset/secondary axes are not in fig.axes at all.
    assert manifest["n_axes"] == 1, f"{manifest['n_axes']} data axes, expected a single chart"


def test_s2_one_bar_per_orchard(manifest):
    values = _bar_values(manifest)
    assert len(values) == len(ORCHARDS), f"{len(values)} bars, expected {len(ORCHARDS)}"


def test_s2_exact_yield_totals(manifest):
    """The point of the task: a wrong filter or a wrong aggregation misses here.

    This is the assertion mutants/sum_crates fails -- it plots [31, 56, 41, 68],
    total crates, where the task asked for kilograms.
    """
    values = _bar_values(manifest)
    assert values == pytest.approx(EXPECTED, rel=1e-6), (
        f"bar heights are {values}, expected {EXPECTED} "
        "(cleared rows only, yield = crates * kilos_per_crate, summed per orchard)"
    )


def test_s2_orchards_in_alphabetical_order(manifest):
    """Explicitly ordered by the instructions, so a self-consistent permutation
    (e.g. sorted by yield descending) must still fail."""
    seen = _ordered_orchards(manifest)
    assert seen == ORCHARDS, f"x tick labels read {seen}, the task requires {ORCHARDS}"


def test_s2_each_bar_carries_its_own_orchards_value(manifest):
    """Ties the labels to the numbers: bar i must be orchard i's yield.

    Worth stating separately. The previous two tests, together, still pass a
    chart with the right four heights and the right four labels attached to
    each other in the wrong pairing.
    """
    values = _bar_values(manifest)
    seen = _ordered_orchards(manifest)
    assert len(seen) == len(values), f"{len(seen)} orchard labels for {len(values)} bars"
    paired = dict(zip(seen, values))
    expected = dict(zip(ORCHARDS, EXPECTED))
    assert paired == pytest.approx(expected, rel=1e-6), f"label-to-height pairing is {paired}"


def test_s2_y_axis_starts_at_zero(manifest):
    """A truncated baseline exaggerates differences between bars; the
    instructions forbid it, so the verifier has to be able to see it."""
    low, high = _axes(manifest)["ylim"]
    span = abs(high - low) or 1.0
    assert low <= 0.02 * span, (
        f"the y axis starts at {low}, not zero, so the bar lengths are not proportional"
    )


def test_s2_bars_are_vertical(manifest):
    # BarContainer.orientation is authoritative. Inferring orientation from
    # rectangle geometry misclassifies wide, short bars as horizontal.
    containers = [c for c in _axes(manifest).get("containers", []) if c.get("type") == "bar"]
    orientations = {c.get("orientation") for c in containers}
    assert orientations == {"vertical"}, (
        f"bars are {orientations}; the task puts orchards on the x axis and yield on the y axis"
    )


def test_s2_titled_and_both_axes_labelled(manifest):
    axes = _axes(manifest)
    assert axes["title"].strip(), "the chart has no title"
    assert axes["xlabel"].strip(), "the x axis has no label"
    assert axes["ylabel"].strip(), "the y axis has no label"


# =============================================================================
# S3 -- PIXEL-IDENTITY ANTI-FORGERY
#
# S2 grades the SCRIPT. Nothing in S2 grades the IMAGE, so an agent can leave a
# perfectly correct plot.py on disk next to a figure.png rendered from entirely
# different numbers, and score 1.0. That is mutants/forgery, and this one test
# is the only thing that stops it.
#
# The cost is a reproducibility requirement: the same script must render the
# same bytes twice. The Dockerfile pre-builds the font cache and _reexecute()
# pins SOURCE_DATE_EPOCH to make that true. If you adopt this idea in your own
# task and the check flaps, that reproducibility is what broke.
# =============================================================================
def test_s3_delivered_png_matches_a_fresh_render(manifest):
    import numpy as np
    from PIL import Image

    produced = Path(manifest["_png"])
    assert produced.exists(), "the re-run emitted a manifest but no PNG beside it"
    assert DELIVERED_BACKUP.exists(), "no delivered figure was captured before the re-run"
    _unlaundered(DELIVERED_BACKUP)

    # (a) The image the re-run left on disk must be the image savefig wrote.
    # The hook hashes the bytes from inside savefig, which is the only place
    # they can be seen before the script gets to touch them again: a script
    # that saves the right chart, renders a wrong one to polished.png and then
    # shutil.move()s it over figure.png is caught here and nowhere else --
    # every pixel comparison below would be comparing the impostor to itself.
    recorded = manifest.get("image_sha256")
    assert recorded, "the savefig hook recorded no digest for the saved image"
    on_disk = _sha256(produced)
    assert on_disk == recorded, (
        f"{produced.name} was replaced after plot.py saved it: savefig wrote bytes "
        f"hashing to {recorded[:12]}..., but the file left behind hashes to "
        f"{on_disk[:12]}.... The delivered figure is not the chart the script draws."
    )

    # (b) ...and the figure the agent handed in must be that same image.
    if _sha256(DELIVERED_BACKUP) == recorded:
        return

    delivered = np.asarray(Image.open(DELIVERED_BACKUP).convert("RGB")).astype(int)
    fresh = np.asarray(Image.open(produced).convert("RGB")).astype(int)
    assert delivered.shape == fresh.shape, (
        f"the script renders {fresh.shape} but figure.png is {delivered.shape}; "
        "figure.png was not produced by this script"
    )
    # Compare the FRACTION of pixels that differ at all, not the mean absolute
    # difference. A mean is an average over a mostly-white canvas, so it hides
    # real errors: on this chart, getting Willowdrift wrong by 10 kg measures a
    # mean absolute difference of 0.108 out of 255 -- comfortably under a 0.5
    # mean tolerance -- and on a thirty-bar chart or a line plot one 40%-wrong
    # value averages away to nothing. A fraction does not dilute: that same
    # 10 kg error repaints 0.0008 of the canvas, eight times the threshold
    # below, while a stray anti-aliased pixel or two does not. (Measured in
    # this task's image; the forgery mutant repaints 0.019 of it.)
    difference = np.abs(delivered - fresh)
    differing = float((difference.sum(axis=2) > 0).mean())
    print(f"[s3] fraction of pixels differing, delivered vs re-render = {differing:.6f}")
    assert differing < 1e-4, (
        f"figure.png is not what plot.py renders ({differing:.2%} of pixels differ). "
        "Either the delivered figure was not produced by the delivered script, or the "
        "script does not render reproducibly -- a random colour, a timestamp in the "
        "title or an unseeded jitter will do it. This task requires a script whose "
        "output is stable across runs."
    )


# =============================================================================
# S4 -- INPUT-PERTURBATION PROBE
#
# The highest-value idea in this file, and the cheapest of the expensive ones.
#
# Consider a plot.py that reads:  values = [558.0, 420.0, 1230.0, 816.0]
# It never opens harvest_log.csv. It is not a solution to the task -- it is the
# answer copied in by hand. And it passes S1 (files are there), S2 (the numbers
# are right), S3 (it does render the figure it handed in) and S5 (the sidecar
# agrees). Every check above is blind to it. That is mutants/hardcoded.
#
# The fix is to stop asking "is the output right" and start asking "does the
# output DEPEND on the input": change the input, re-run, and require the answer
# to follow. Any task with a data file can do this in about fifteen lines.
# =============================================================================
def test_s4_totals_track_the_input_file(perturbed_manifest):
    values = _bar_values(perturbed_manifest)
    assert values == pytest.approx(PERTURBED, rel=1e-6), (
        f"with one extra cleared Cinderpeak haul of 8 crates at 7.50 kg the chart should read "
        f"{PERTURBED}, but the script still plots {values}; it is not reading harvest_log.csv"
    )


# =============================================================================
# S5 -- CROSS-CHECK THE AGENT'S OWN DECLARED NUMBERS
#
# The instructions require /app/plotted_values.json, written from the same
# variables that get plotted. Asking for a machine-readable statement of the
# answer alongside the artifact is a cheap trick worth reusing: it gives the
# verifier a second, independent view of what the agent believed, and any
# disagreement between the two is a bug in the solution by definition.
# =============================================================================
def test_s5_sidecar_matches_key_and_chart(manifest):
    # The snapshot, not /app: by the time this runs the script has been
    # re-executed twice, and a script that writes "/app/plotted_values.json" by
    # absolute path has overwritten the delivered file with the perturbed run's
    # numbers. Grade what was handed in.
    assert DELIVERED_SIDECAR.exists(), "no /app/plotted_values.json"
    declared = json.loads(_unlaundered(DELIVERED_SIDECAR).read_text())
    assert isinstance(declared, dict), f"plotted_values.json holds a {type(declared).__name__}"
    assert sorted(declared) == ORCHARDS, f"sidecar keys are {sorted(declared)}, expected {ORCHARDS}"
    # The instructions call the schema normative and say the values are JSON
    # numbers, "not a string". Check the type rather than coercing with
    # float(v): coercion passes {"Brambleholt": "558.0"}, which the schema
    # forbids, and turns {"Brambleholt": "558 kg"} into an uncaught ValueError
    # instead of a readable schema complaint. isinstance(True, int) is True,
    # hence the bool exclusion -- JSON true is not a yield figure.
    for orchard, value in declared.items():
        assert isinstance(value, (int, float)) and not isinstance(value, bool), (
            f"plotted_values.json[{orchard!r}] is {value!r} ({type(value).__name__}); "
            "the schema requires a JSON number, not a string"
        )
    numbers = {orchard: float(value) for orchard, value in declared.items()}
    # (a) the declared numbers must be the right numbers...
    expected = dict(zip(ORCHARDS, EXPECTED))
    assert numbers == pytest.approx(expected, rel=1e-6), (
        f"plotted_values.json declares {declared}"
    )
    # (b) ...and they must be the numbers the chart actually draws.
    drawn = dict(zip(_ordered_orchards(manifest), _bar_values(manifest)))
    assert numbers == pytest.approx(drawn, rel=1e-6), (
        f"plotted_values.json says {declared} but the chart draws {drawn}"
    )
