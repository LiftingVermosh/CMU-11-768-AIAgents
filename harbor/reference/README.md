# reference/ — optional notes on strong verifiers

**Optional.** These notes do not affect your grade; checking that the output is a
valid PNG is sufficient. They document a less obvious technique for detecting
incorrect data and chart contents with a deterministic verifier.

## The one idea

Direct pixel analysis is insufficient because a PNG does not preserve semantic
information such as scale, tick text or series identity. Pixels can show that a
blue region is 340 pixels tall, but not whether it represents 1,230 or 1,231 kg
of Mistfen yield.

So do not read the picture:

> **Re-execute the agent's plotting script with
> `matplotlib.figure.Figure.savefig` hooked, and assert over a JSON description
> of the artist tree the script built.**

`install_savefig_hook()` (in `harbor/example/tests/figure_manifest.py`) wraps
`savefig` so every call also writes `<stem>.manifest.json` next to the image.
`harbor/example/tests/sitecustomize.py` is how the hook reaches code you do not
control: CPython imports a module named `sitecustomize` at start-up if it is
anywhere on `PYTHONPATH`, so the hook is live before the agent's script runs its
first line. Nothing is installed in the agent's sandbox — this happens only at
verify time, in a throw-away copy of the workspace.

The manifest is flat and diffable (abridged here; the real one carries more
per-axes keys):

```jsonc
{"n_axes": 1, "axes": [{
  "title": "Cleared yield by orchard",
  "xlabel": "Orchard", "ylabel": "Cleared yield (kg)",
  "xlim": [-0.5900000000000001, 3.5900000000000003], "ylim": [0.0, 1353.0],
  "xticklabels": ["Brambleholt", "Cinderpeak", "Mistfen", "Willowdrift"],
  "containers": [{"type": "bar", "values": [558.0, 420.0, 1230.0, 816.0]}],
  "patches": [ /* one per bar: x, y, width, height, colour */ ]}]}
```

So "bar heights are `[558.0, 420.0, 1230.0, 816.0]`" is a one-line assertion with
a readable failure message, and "the orchards are in alphabetical order" is
another. Floats are floats — that `xlim` really is `-0.5900000000000001` — so
compare with `pytest.approx`, never `==`.

## The anti-forgery ordering — get it wrong and it fails SILENTLY

Re-execution proves something only if the re-run cannot be confused with the
submission. This order is not stylistic:

1. **Back up the submitted `figure.png` before modifying the workspace.** Create
   a new temporary directory outside `/app` with `mkdtemp()` rather than using a
   predictable path such as `/tmp/delivered.png`. Store the file's SHA-256 digest
   in the verifier process. The re-run executes as root and may be able to alter
   files on disk, but it cannot change a digest already held in verifier memory.
2. **Copy `/app`** to a throw-away directory.
3. **Delete every `*.png` and `*.manifest.json` from the copy** — every one, not
   just `figure.png`.
4. **Re-run the agent's script** inside the copy, with `PYTHONPATH` pointing at
   the directory holding `sitecustomize.py`.
5. **Accept only outputs whose `mtime` is at or after the run start.** Record the
   start time *before* launching the subprocess.
6. **Only now compare** — manifest values against your answer key, and the fresh
   PNG against the step-1 backup.

If step 1 or step 3 is wrong, the verifier may compare the submitted figure with
itself. A backup inside `/app` can be deleted or overwritten. A stale figure left
in the copied workspace can also be mistaken for fresh output if the script
writes under another name or produces nothing. In either case, the content and
pixel checks may pass even when `plot.py` and `figure.png` represent different
data.

Step 5 prevents stale files from being treated as fresh output. Test this
behavior with a deliberate forgery mutant and confirm that it scores 0.

## Sharp edges

Manifest files are named from the image **stem**. Therefore, both `figure.svg`
and `figure.pdf` produce `figure.manifest.json`. A check that specifically
expects a PNG may then report the misleading error *"the re-run emitted a
manifest but no PNG beside it"*. If a script saves both `figure.png` and
`figure.pdf`, both saves also target the same manifest path, so the second
manifest overwrites the first.

The delivered-versus-fresh pixel check (`test_s3_*` in the example) allows fewer
than one pixel in 10,000 to differ. Omit this check if the figure can vary between
renders, for example because it contains a timestamp, jitter or randomly selected
colours. In testing, a solution that chose randomly among four bar colours passed
only when both renders happened to select the same colour. Failed comparisons
differed in 28.88% of pixels. This variability affects only the pixel comparison,
not the manifest-based content assertions.

## If you want to use it

harbor copies only a task's `tests/` directory into the container, so the library
has to live there — copy, do not symlink or import from outside:

```bash
cp harbor/example/tests/figure_manifest.py harbor/example/tests/sitecustomize.py \
   harbor/tasks/<task_id>/tests/
```

That copy's module docstring is written for the worked example, so it names the
example's strategies; the code is general.
`harbor/example/tests/test_state.py` implements all of the above in the right
order, and `harbor/example/mutants/` holds the forgery and hard-coded-values
attacks it defends against.
