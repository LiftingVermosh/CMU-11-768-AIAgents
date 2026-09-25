"""The instrumentation hook -- how the verifier sees inside the agent's figure.

CPython imports a module named ``sitecustomize`` automatically at interpreter
start-up, before a single line of user code runs. Put a file with that name
anywhere on ``PYTHONPATH`` and you have a way to patch the world out from under
a program you did not write and cannot modify.

That is exactly what the verifier needs. ``_reexecute()`` in test_state.py runs
the agent's ``plot.py`` with ``PYTHONPATH`` pointing at a private copy of this
file and ``figure_manifest.py`` -- NOT at /tests, which also holds the answer
key -- so this file loads first and patches ``Figure.savefig`` to also dump a
JSON description of the figure's artist tree next to every image the script
saves. The agent's script is not edited, is not told, and behaves identically --
it just leaves a machine-readable record of what it drew.

Two properties worth copying if you use this trick in your own task:

*   Nothing is installed in the agent's sandbox. The hook exists only at verify
    time, in a throw-away copy of the workspace, so it cannot be discovered or
    disabled during the agent phase.
*   The import is wrapped in a bare ``except``. A broken hook must degrade to
    "no manifest", never to "the program under test crashed". Instrumentation
    that can break the thing it observes is worse than no instrumentation.
    (The verifier still fails closed: no manifest means no evidence, and
    ``_reexecute`` asserts that a manifest was produced.)
"""

try:
    from figure_manifest import install_savefig_hook

    install_savefig_hook()
except Exception:  # pragma: no cover - never let the hook break the re-run
    pass
