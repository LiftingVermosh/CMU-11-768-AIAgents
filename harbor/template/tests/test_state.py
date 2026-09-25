"""Verifier for this task.  Runs as root in the agent's container after the
agent phase; /app is the agent's finished workspace and /tests is this
directory, copied in after the agent finished.  The agent never saw it -- but
at verify time both directories are writable, so if you re-run the agent's
script from here, keep this file off its import path: it is the answer key.

Three worked checks are below -- keep them, extend them.  Then delete the
sentinel at the bottom, which is the only thing standing between you and a
verifier that passes an empty submission.

What you can reach from here, cheapest first:
  * the delivered files (exists, size, decodes, parses)
  * the agent's own script, which is still on disk -- you may re-run it
  * anything you can compute from the input data yourself

What a PNG will NOT tell you: bar heights, tick text, series identity.  Say so
in your report; you are not required to solve it.
"""

import json
from pathlib import Path

import pytest

APP = Path("/app")
FIGURE = APP / "figure.png"           # TODO: the figure your task asks for
SIDECAR = APP / "plotted_values.json"  # required: ASSIGNMENT.md, Part 3


# --------------------------------------------------------------- worked checks
def test_figure_exists():
    assert FIGURE.exists(), f"no figure at {FIGURE}; the task requires one"


def test_figure_is_a_valid_nonblank_png():
    """Catches a truncated write, a saved-but-empty axes, and a wrong format."""
    import numpy as np
    from PIL import Image

    size = FIGURE.stat().st_size
    assert size > 1000, f"{FIGURE} is only {size} bytes, so it is not a real chart"
    with Image.open(FIGURE) as image:
        image.verify()          # decodes the whole file; raises on corruption
    with Image.open(FIGURE) as image:
        assert image.format == "PNG", f"{FIGURE} is a {image.format}, not a PNG"
        assert min(image.size) > 100, f"{FIGURE} is {image.size}, too small to read"
        pixels = np.asarray(image.convert("RGB")).reshape(-1, 3)
    distinct = len(np.unique(pixels, axis=0))
    assert distinct > 4, f"{FIGURE} has {distinct} distinct colours: it is a blank canvas"


def test_sidecar_parses_and_has_the_promised_shape():
    """If your instruction.md promises a JSON sidecar, hold it to its schema."""
    if SIDECAR is None:
        pytest.skip("this task does not ask for a sidecar")
    assert SIDECAR.exists(), f"no {SIDECAR}; instruction.md asks for it"
    declared = json.loads(SIDECAR.read_text())   # raises on malformed JSON
    assert isinstance(declared, dict), f"{SIDECAR} holds a {type(declared).__name__}, expected an object"
    assert declared, f"{SIDECAR} is an empty object"
    # TODO: assert the actual keys and value types your instruction.md promises,
    # e.g.  assert sorted(declared) == ["alpha", "beta", "gamma"]
    for key, value in declared.items():
        # Check the type, do not coerce with float(v): coercion passes the
        # string "12.5" that your schema forbids, and turns "$12.5" into an
        # uncaught ValueError.  isinstance(True, int) is True, hence the bool.
        assert isinstance(value, (int, float)) and not isinstance(value, bool), (
            f"{SIDECAR}[{key!r}] is {value!r} ({type(value).__name__}); "
            "the schema says a JSON number"
        )


# ------------------------------------------------------------------- your checks
# TODO: add the checks that are actually about YOUR task's content -- the
# numbers, the ordering, the encoding, the labels.  Then delete the sentinel.


def test_zzz_template_sentinel_must_be_removed():
    pytest.fail(
        "HARBOR-TEMPLATE-SENTINEL: this verifier has not been written yet.\n"
        "The three checks above only prove a non-blank PNG exists -- an agent "
        "that plots the wrong thing still passes them.\n"
        "Add the content checks your task needs, then delete this test.\n"
        "It is here so that an unfinished task scores 0 instead of a false 1.0."
    )
