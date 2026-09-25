"""Structured capture of what a Matplotlib figure actually contains.

A rendered PNG is opaque: to know whether a bar is the right height you would
have to read pixels. This module serialises the figure's artist tree to JSON at
save time, so both the grading pipeline and the student validator can check
plotted values, encodings, labels and scales exactly rather than by inference.

Two entry points:

``manifest_from_figure(fig)``
    Build a manifest dict from a live ``Figure``.

``install_savefig_hook()``
    Patch ``Figure.savefig`` so every save also writes ``<stem>.manifest.json``
    next to the image, recording the sha256 of the bytes that save produced.
    Used inside the agent sandbox, where we do not control the code being run.
    That digest is what lets a verifier tell "this image is what that save
    wrote" from "something was written over the top of it afterwards".

The schema is intentionally flat and JSON-native so it can be diffed, hashed and
asserted against without importing Matplotlib.

You do not need to read this file to understand the example. It is the library
that makes strategy S2 in ``test_state.py`` possible, and it is long because
Matplotlib hides data in a different place for nearly every chart type -- the
comments through the ``_patches`` / ``_collections`` / ``_containers`` readers
are a catalogue of those hiding places, collected the hard way. Skim it when a
chart type of yours comes out of the manifest looking empty.

WHY IT LIVES HERE. This is the only copy, and it sits inside ``tests/`` rather
than somewhere shared because harbor copies exactly this directory into the
container and nothing else -- an import reaching out of the task tree would not
resolve at verify time. To use it in a task of your own, copy this file and
``sitecustomize.py`` into that task's ``tests/`` directory as well.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
from pathlib import Path
from typing import Any

MANIFEST_VERSION = "1.0"
MAX_POINTS = 20_000  # guard against a scatter of a million points
MAX_OUTLINES = 50  # violin bodies and area bands, not hexbin cells
MAX_PATHS = 200  # a line collection can hold many segments


def _num(value: Any) -> Any:
    """Coerce numpy scalars to JSON-safe floats; keep non-finite as strings."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return "nan"
    if math.isinf(result):
        return "inf" if result > 0 else "-inf"
    return result


def _seq(values: Any) -> list[Any]:
    try:
        items = list(values)
    except TypeError:
        return []
    if len(items) > MAX_POINTS:
        items = items[:MAX_POINTS]
    return [_num(item) for item in items]


def summarise(values: list[Any]) -> dict[str, Any] | None:
    """Compact description of a numeric series.

    Full point lists make a manifest exact but far too large to put in a model
    prompt. Every series therefore also carries a digest: a validator can reason
    over the digest and drop to the raw values only for the checks that need
    them.
    """
    finite = [value for value in values if isinstance(value, (int, float))]
    if not finite:
        return None
    ordered = sorted(finite)
    midpoint = len(ordered) // 2
    median = (
        ordered[midpoint]
        if len(ordered) % 2
        else (ordered[midpoint - 1] + ordered[midpoint]) / 2
    )
    return {
        "n": len(values),
        "min": min(finite),
        "max": max(finite),
        "mean": sum(finite) / len(finite),
        "median": median,
        "sum": sum(finite),
        "head": finite[:5],
        "tail": finite[-5:],
        "monotonic": all(a <= b for a, b in zip(finite, finite[1:]))
        or all(a >= b for a, b in zip(finite, finite[1:])),
    }


def _colour(value: Any) -> str | None:
    try:
        from matplotlib.colors import to_hex

        return to_hex(value, keep_alpha=False)
    except (ImportError, ValueError, TypeError):
        return None


def _text(artist: Any) -> str:
    try:
        return str(artist.get_text())
    except AttributeError:
        return ""


def _lines(axes: Any) -> list[dict[str, Any]]:
    out = []
    for line in axes.get_lines():
        # Line3D.get_xydata() drops z without saying so.
        data_3d = getattr(line, "get_data_3d", None)
        if callable(data_3d):
            try:
                xs, ys, zs = data_3d()
                out.append(
                    {
                        "type": "line3d",
                        "label": line.get_label(),
                        "x": _seq(xs),
                        "y": _seq(ys),
                        "z": _seq(zs),
                        "y_summary": summarise(_seq(ys)),
                        "z_summary": summarise(_seq(zs)),
                        "colour": _colour(line.get_color()),
                        "linestyle": str(line.get_linestyle()),
                        "marker": str(line.get_marker()),
                    }
                )
                continue
            except (TypeError, ValueError):
                pass
        data = line.get_xydata()
        out.append(
            {
                "type": "line",
                "label": line.get_label(),
                "x": _seq(point[0] for point in data),
                "y": _seq(point[1] for point in data),
                "x_summary": summarise(_seq(point[0] for point in data)),
                "y_summary": summarise(_seq(point[1] for point in data)),
                "colour": _colour(line.get_color()),
                "linestyle": str(line.get_linestyle()),
                "linewidth": _num(line.get_linewidth()),
                "marker": str(line.get_marker()),
                # ax.step() and ax.plot() of the same samples differ only here.
                "drawstyle": str(line.get_drawstyle()),
            }
        )
    return out


def _patches(axes: Any) -> list[dict[str, Any]]:
    from matplotlib.patches import PathPatch, Polygon, Rectangle, Wedge

    try:
        from matplotlib.patches import StepPatch
    except ImportError:  # pragma: no cover - older Matplotlib
        StepPatch = ()

    out = []
    for patch in axes.patches:
        if StepPatch and isinstance(patch, StepPatch):
            # ax.stairs() produces only this; without it the axes looks empty.
            # StairData is a 3-tuple (values, edges, baseline) in current
            # Matplotlib; unpack positionally rather than assuming a pair.
            data = patch.get_data()
            values, edges = data[0], data[1]
            out.append(
                {
                    "type": "stairs",
                    "label": patch.get_label(),
                    "y": _seq(values),
                    "edges": _seq(edges),
                    "y_summary": summarise(_seq(values)),
                    "colour": _colour(patch.get_facecolor()),
                }
            )
            continue
        if isinstance(patch, Polygon) and not isinstance(patch, Rectangle):
            # histtype="step" and fill_between leave a single Polygon and no
            # containers, bars or lines: without this branch they are invisible.
            vertices = patch.get_xy()
            out.append(
                {
                    "type": "polygon",
                    "label": patch.get_label(),
                    "x": _seq(point[0] for point in vertices),
                    "y": _seq(point[1] for point in vertices),
                    "y_summary": summarise(_seq(point[1] for point in vertices)),
                    "colour": _colour(patch.get_facecolor()),
                    "filled": bool(patch.get_fill()),
                }
            )
        elif isinstance(patch, Rectangle):
            out.append(
                {
                    "type": "bar",
                    "label": patch.get_label(),
                    "x": _num(patch.get_x()),
                    "y": _num(patch.get_y()),
                    "width": _num(patch.get_width()),
                    "height": _num(patch.get_height()),
                    "colour": _colour(patch.get_facecolor()),
                }
            )
        elif isinstance(patch, PathPatch):
            # boxplot(patch_artist=True) draws box bodies as PathPatch.
            vertices = patch.get_path().vertices
            out.append(
                {
                    "type": "pathpatch",
                    "label": patch.get_label(),
                    "x": _seq(point[0] for point in vertices),
                    "y": _seq(point[1] for point in vertices),
                    "y_summary": summarise(_seq(point[1] for point in vertices)),
                    "colour": _colour(patch.get_facecolor()),
                }
            )
        elif isinstance(patch, Wedge):
            out.append(
                {
                    "type": "wedge",
                    "label": patch.get_label(),
                    "theta1": _num(patch.theta1),
                    "theta2": _num(patch.theta2),
                    "radius": _num(patch.r),
                    "colour": _colour(patch.get_facecolor()),
                }
            )
    return out


def _containers(axes: Any) -> list[dict[str, Any]]:
    """Grouped/stacked bar series, which patches alone cannot express.

    Matplotlib puts the series label on the BarContainer; every Rectangle
    inside reports "_nolegend_", so series identity is lost if you only read
    ``ax.patches``. Note the ordering trap: ``ax.bar(..., yerr=...)`` yields
    ``[ErrorbarContainer, BarContainer]`` -- the error bars come first -- so
    never index ``containers[0]``, filter on ``type``.
    """
    out = []
    for container in getattr(axes, "containers", []):
        entry: dict[str, Any] = {
            "type": type(container).__name__.lower().replace("container", ""),
            "label": container.get_label(),
        }
        children = getattr(container, "patches", None)
        if children:
            # BarContainer.orientation is authoritative. Inferring it from
            # geometry gets histograms wrong: wide, short bins look horizontal.
            horizontal = getattr(container, "orientation", "vertical") == "horizontal"
            entry["orientation"] = "horizontal" if horizontal else "vertical"
            entry["values"] = _seq(
                patch.get_width() if horizontal else patch.get_height() for patch in children
            )
            entry["offsets"] = _seq(
                patch.get_y() if horizontal else patch.get_x() for patch in children
            )
            entry["baselines"] = _seq(
                patch.get_x() if horizontal else patch.get_y() for patch in children
            )
            entry["values_summary"] = summarise(entry["values"])
        datavalues = getattr(container, "datavalues", None)
        if datavalues is not None:
            entry["datavalues"] = _seq(datavalues)
        out.append(entry)
    return out


def _collections(axes: Any) -> list[dict[str, Any]]:
    out = []
    for collection in axes.collections:
        entry: dict[str, Any] = {
            "type": type(collection).__name__.lower(),
            "label": collection.get_label(),
        }
        offsets = getattr(collection, "get_offsets", None)
        if callable(offsets):
            try:
                points = offsets()
                entry["x"] = _seq(point[0] for point in points)
                entry["y"] = _seq(point[1] for point in points)
                entry["x_summary"] = summarise(entry["x"])
                entry["y_summary"] = summarise(entry["y"])
            except (TypeError, IndexError, ValueError):
                pass
        array = getattr(collection, "get_array", None)
        if callable(array):
            values = array()
            if values is not None:
                entry["values"] = _seq(values.ravel() if hasattr(values, "ravel") else values)
                entry["values_summary"] = summarise(entry["values"])
        # get_offsets() returns a single dummy point for poly and line
        # collections, so violin bodies, stacked areas and error-bar extents
        # were previously invisible. Their geometry lives in the paths.
        segments = getattr(collection, "get_segments", None)
        if callable(segments):
            try:
                entry["segments"] = [
                    [[_num(point[0]), _num(point[1])] for point in segment]
                    for segment in segments()[:MAX_PATHS]
                ]
            except (TypeError, ValueError, IndexError):
                pass
        elif callable(getattr(collection, "get_paths", None)):
            try:
                paths = collection.get_paths()
                # A violin body or an area band is a handful of many-vertex
                # outlines; a hexbin or a scatter is thousands of identical
                # marker shapes, whose geometry says nothing the offsets and
                # values do not already say.
                outlines = len(paths) <= MAX_OUTLINES and any(
                    len(path.vertices) > 4 for path in paths
                )
                if outlines:
                    entry["paths"] = [
                        {
                            "x": _seq(vertex[0] for vertex in path.vertices),
                            "y": _seq(vertex[1] for vertex in path.vertices),
                            "y_summary": summarise(_seq(vertex[1] for vertex in path.vertices)),
                        }
                        for path in paths
                    ]
            except (TypeError, ValueError, AttributeError, IndexError):
                pass

        # 3-D scatter: get_offsets() silently returns the 2-D projection, so z
        # is invisible without reaching for the private attribute. A wrong z is
        # exactly the kind of error that looks fine from one viewing angle.
        offsets3d = getattr(collection, "_offsets3d", None)
        if offsets3d is not None:
            try:
                xs, ys, zs = offsets3d
                entry["x"] = _seq(xs)
                entry["y"] = _seq(ys)
                entry["z"] = _seq(zs)
                entry["x_summary"] = summarise(entry["x"])
                entry["y_summary"] = summarise(entry["y"])
                entry["z_summary"] = summarise(entry["z"])
            except (TypeError, ValueError):
                pass

        sizes = getattr(collection, "get_sizes", None)
        if callable(sizes):
            try:
                entry["sizes"] = _seq(sizes())
            except (TypeError, ValueError):
                pass
        cmap = getattr(collection, "get_cmap", None)
        if callable(cmap):
            try:
                entry["cmap"] = cmap().name
            except (AttributeError, TypeError):
                pass
        out.append(entry)
    return out


def _images(axes: Any) -> list[dict[str, Any]]:
    out = []
    for image in axes.get_images():
        entry: dict[str, Any] = {"type": "image"}
        try:
            entry["cmap"] = image.get_cmap().name
        except AttributeError:
            pass
        try:
            entry["clim"] = [_num(v) for v in image.get_clim()]
        except (AttributeError, TypeError):
            pass
        try:
            array = image.get_array()
            entry["shape"] = list(getattr(array, "shape", []) or [])
            entry["values"] = _seq(array.ravel())
            entry["values_summary"] = summarise(entry["values"])
        except (AttributeError, ValueError):
            pass
        out.append(entry)
    return out


def _legend(axes: Any) -> dict[str, Any] | None:
    legend = axes.get_legend()
    if legend is None:
        return None
    return {
        "labels": [_text(item) for item in legend.get_texts()],
        "visible": bool(legend.get_visible()),
    }


def _annotations(axes: Any) -> list[dict[str, Any]]:
    out = []
    for text in axes.texts:
        body = _text(text)
        if not body.strip():
            continue
        try:
            position = [_num(coordinate) for coordinate in text.get_position()]
        except (AttributeError, TypeError):
            position = []
        entry: dict[str, Any] = {"text": body, "position": position}
        # annotate() records the annotated point separately from the label
        # position; without it "the arrow points at Thursday" is undecidable.
        target = getattr(text, "xy", None)
        if target is not None:
            try:
                entry["points_at"] = [_num(coordinate) for coordinate in target]
            except TypeError:
                pass
        out.append(entry)
    return out


def _axes_role(axes: Any) -> str:
    if axes.get_label() == "<colorbar>":
        return "colorbar"
    if getattr(axes, "_axes_locator", None) is not None:
        return "inset"
    return "main"


def _twin_relationship(axes: Any, index: int) -> dict[str, Any]:
    """Classify how this axes overlays another one.

    Position equality alone conflates ``twinx`` with ``twiny``; the shared-axis
    Grouper alone false-positives on ``sharex=True`` subplots. Both together
    give the answer, and which axis is *not* shared says which scale is
    independent -- the distinction a request for "different left and right
    scales" actually turns on.
    """
    siblings_x = axes.get_shared_x_axes().get_siblings(axes)
    siblings_y = axes.get_shared_y_axes().get_siblings(axes)
    overlapping, twin_of, kind = [], None, None
    for other_index, other in enumerate(axes.figure.axes):
        if other is axes:
            continue
        if other.get_position().bounds != axes.get_position().bounds:
            continue
        overlapping.append(other_index)
        shares_x, shares_y = other in siblings_x, other in siblings_y
        if shares_x and not shares_y:
            twin_of, kind = other_index, "twinx"  # independent y scales
        elif shares_y and not shares_x:
            twin_of, kind = other_index, "twiny"  # independent x scales
    return {"overlapping_axes": overlapping, "twin_of": twin_of, "twin_kind": kind}


def _axes_manifest(axes: Any, index: int) -> dict[str, Any]:
    return {
        "index": index,
        "role": _axes_role(axes),
        **_twin_relationship(axes, index),
        "title": _text(axes.title),
        "xlabel": axes.get_xlabel(),
        "ylabel": axes.get_ylabel(),
        # A pie drawn on non-equal aspect is an ellipse, which misreads angles.
        "aspect": str(axes.get_aspect()),
        "projection": getattr(axes, "name", "rectilinear"),
        "yaxis_side": axes.yaxis.get_ticks_position(),
        "xscale": axes.get_xscale(),
        "yscale": axes.get_yscale(),
        "xlim": [_num(v) for v in axes.get_xlim()],
        "ylim": [_num(v) for v in axes.get_ylim()],
        "xticklabels": [_text(t) for t in axes.get_xticklabels()],
        "yticklabels": [_text(t) for t in axes.get_yticklabels()],
        "position": [_num(v) for v in axes.get_position().bounds],
        "legend": _legend(axes),
        "grid_visible": bool(
            any(line.get_visible() for line in axes.get_xgridlines())
            or any(line.get_visible() for line in axes.get_ygridlines())
        ),
        "lines": _lines(axes),
        "patches": _patches(axes),
        "containers": _containers(axes),
        "collections": _collections(axes),
        "images": _images(axes),
        "annotations": _annotations(axes),
    }


def manifest_from_figure(fig: Any) -> dict[str, Any]:
    """Serialise a Matplotlib ``Figure`` into a plain-JSON manifest."""
    # Several properties are only correct after a render pass: scatter face
    # colours are unresolved until update_scalarmappable() runs, and the axis
    # offset text ("x10^6") is empty. Drawing once under Agg is cheap.
    try:
        fig.canvas.draw()
    except Exception:  # noqa: BLE001 - a figure we cannot draw is still worth describing
        pass

    entries = [_axes_manifest(axes, index) for index, axes in enumerate(fig.axes)]
    # secondary_yaxis() and inset_axes() never appear in fig.axes, so a plain
    # len() undercounts; colorbars are in fig.axes but are not data axes, so it
    # also overcounts. Report both the raw list and the corrected count.
    child_axes = sum(len(getattr(axes, "child_axes", []) or []) for axes in fig.axes)
    return {
        "manifest_version": MANIFEST_VERSION,
        "figsize": [_num(v) for v in fig.get_size_inches()],
        "dpi": _num(fig.get_dpi()),
        "suptitle": _text(fig._suptitle) if getattr(fig, "_suptitle", None) else "",
        "n_axes": sum(1 for entry in entries if entry["role"] == "main"),
        "n_axes_raw": len(fig.axes),
        "n_child_axes": child_axes,
        "axes": entries,
    }


def manifest_path_for(image_path: str | Path) -> Path:
    path = Path(image_path)
    return path.with_name(path.stem + ".manifest.json")


def _file_sha256(path: str | Path) -> str | None:
    """Digest of the bytes a save just wrote, or None if they cannot be read."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def install_savefig_hook() -> None:
    """Make every ``Figure.savefig`` also emit a manifest beside the image.

    Idempotent. Failures are swallowed: a manifest is diagnostic output and must
    never break the run being observed.
    """
    from matplotlib.figure import Figure

    if getattr(Figure.savefig, "_emits_manifest", False):
        return

    original = Figure.savefig

    # functools.wraps keeps __qualname__ == "Figure.savefig"; pyplot derives the
    # owning class from it at import time and raises if it is anything else.
    @functools.wraps(original)
    def savefig(self, fname, *args, **kwargs):  # type: ignore[no-untyped-def]
        result = original(self, fname, *args, **kwargs)
        try:
            if isinstance(fname, (str, Path)):
                target = manifest_path_for(fname)
                payload = manifest_from_figure(self)
                # Digest the bytes THIS save wrote, before anything else can
                # touch the file. A later `shutil.move(other, fname)` leaves
                # the manifest in place but swaps the image out from under it,
                # and comparing this digest against the file on disk is the
                # only way to see that happen.
                payload["saved_to"] = str(Path(fname))
                payload["image_sha256"] = _file_sha256(fname)
                target.write_text(json.dumps(payload, indent=2, default=str) + "\n")
        except Exception:  # noqa: BLE001 - diagnostics must not break the run
            pass
        return result

    savefig._emits_manifest = True  # type: ignore[attr-defined]
    savefig.__doc__ = original.__doc__
    Figure.savefig = savefig  # type: ignore[method-assign]
