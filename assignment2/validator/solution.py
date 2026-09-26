"""The validator you write. This is the only file you need to modify.

Each function evaluates a single run object and returns the errors it finds.
An empty list means that no errors were found. `validator/runner.py` defines
what a run object contains, and `ASSIGNMENT.md` defines the four error families you may report.

Design notes
------------
Every choice here follows from how the validator is scored: a per-family MCC over
four families that the ground truth leaves badly imbalanced (71 wrong_chart runs
against 12 execution_failure ones), averaged into one macro-MCC.

1. Anything derivable from the run's own artifacts is decided in code, not asked.
   Whether a figure exists is a fact about the run; the baseline spent a model call
   on it and bought 33 false positives, because the model would answer YES while
   its own explanation said the agent had succeeded.

2. Nothing open-ended is asked of the model. "Does the figure fail to follow any
   part of the requested chart design?" invites a holistic impression, and the
   baseline's reward for it was 66 missed wrong_chart runs out of 71. The
   instruction is instead decomposed into explicit requirements, and each is
   checked on its own line.

3. The model is asked to quote, not to judge. Every verdict has to carry the
   instruction's wording and what is visible in the figure, which turns a
   judgement into a lookup and makes a invented verdict expensive.

Cost is 3 model calls per run with a figure (decompose, audit data, audit chart)
plus one more for readability -- the same four the baseline spent, with the
execution-failure call it wasted now paying for the decomposition instead.
"""

from __future__ import annotations

import base64
import io
import json
import re

from PIL import Image

from validator.model import complete
from validator.prediction import Error, ErrorFamily
from validator.runner import Run

#: The audits answer one line per requirement; the decomposition needs about a
#: line per requirement too. Truncation only costs recall (parsing stops at the
#: last complete line), never correctness, so these are generous rather than tight.
EXTRACT_TOKENS = 700
AUDIT_TOKENS = 900
READABILITY_TOKENS = 400

#: How much of the agent's own code to put in front of the model.
CODE_LIMIT = 6000
OMISSION = "\n\n[... middle of the script omitted to fit the prompt ...]\n\n"
NO_COMMANDS = "(the trajectory recorded no shell commands)"

#: A requirement line is "<n>. <FAMILY> | <text>". Anchoring the family token to
#: the line start is what keeps a chatty answer from being read as a requirement.
_REQUIREMENT_RE = re.compile(
    r"^\s*[-*]?\s*\**\s*\d+\s*[.):]?\s*\**\s*"
    r"(WRONG_DATA|WRONG_CHART)\b\s*[\|:\-—]*\s*(.*)$",
    re.IGNORECASE,
)

#: A verdict line is "<n>. <VERDICT> | <evidence>". The verdict must sit
#: immediately after the number; a line where it does not is skipped rather than
#: guessed at, because a mis-read line is a wrong label and a skipped line is
#: only a missed one. Longest alternatives first so "NOT MET" wins over "MET".
_VERDICT_RE = re.compile(
    r"^\s*[-*]?\s*\**\s*\d+\s*[.):]?\s*\**\s*"
    r"(VIOLATED|INCORRECT|MISSING|NOT MET|FAILED|FAIL|WRONG|"
    r"SATISFIED|CORRECT|PASS|OK|MET)\b"
    r"(.*)$",
    re.IGNORECASE,
)
_VIOLATION_WORDS = frozenset(
    {"VIOLATED", "INCORRECT", "MISSING", "NOT MET", "FAILED", "FAIL", "WRONG"}
)

#: A defect line is "DEFECT | <check> | <quoted text> | <where>".
_DEFECT_RE = re.compile(r"^\s*[-*]?\s*DEFECT\s*\|(.*)$", re.IGNORECASE)


# --- prompting --------------------------------------------------------------- #

_EXTRACT_PROMPT = """You are auditing a chart against the instructions that produced it.

Instructions:
{instructions}

List every explicit, checkable requirement in the instructions, one per line, in exactly this form:

<n>. <FAMILY> | <the requirement>

FAMILY is one of two words, chosen by what the requirement is about:

wrong_data   The values that must be plotted: a data range or step, an arithmetic or
             transformation step, a filter that drops rows, a series, category or curve that
             has to appear (or has to stay out), or which variable a visual quantity must
             encode.
wrong_chart  The way the chart is drawn: chart type, grid or panel layout, axis scale,
             axis limits, tick labels or axis titles, colormap or colours, legend, markers,
             line style, label rotation, output size.

The boundary in practice, since it is where this decomposition goes wrong most often: a
requirement that names a series by its colour is wrong_data when what it constrains is which
values are plotted ("the blue curve must connect the 2015 points"), and wrong_chart when what
it constrains is how the drawing looks ("the interface line must be green"). The same test
settles geometry and markers, which are otherwise mistaken for data because they are phrased in
terms of the plotted points: "the line must be vertical at x = 0", "the panels must form a 2x1
grid", "the data points must be marked with circles" all constrain how the chart is drawn and
are wrong_chart, even though the sentence names the data.

Rules:
- Only requirements the instructions actually state. Never invent one.
- Split a compound sentence into one item per check.
- Skip anything that cannot be checked by looking at a finished figure.
Output the numbered lines only, nothing before or after."""


_DATA_AUDIT_PROMPT = """A chart was produced from the instructions below. Decide whether the DATA it plots is right.

Instructions:
{instructions}

Requirements to check, one at a time:
{items}

The code the agent ran:
{code}

For each numbered requirement above, answer on its own line in exactly this form:

<n>. OK | <what you checked>
<n>. VIOLATED | <what the instructions ask> but <what the chart actually plots>

Quote the values, series names, ranges or numbers you compared. Report a violation only when the
instructions state a concrete value, series, filter or transformation that you can quote, and you
can say what the chart shows instead. If the instructions leave the choice to whoever draws the
chart -- an undefined variable, a styling preference -- that is not a violation. Answer OK only
after checking that requirement against the chart or the code, never because the chart looks
plausible. Do not report a requirement that is not in the list above.

Compare a number only when it is printed in the figure or stated in the code. Do not estimate a
value from a bar's height, a wedge's angle or a point's position and then report the difference:
a number inferred from rendered geometry is a guess, and a mismatch you guessed is not evidence.

Some requirements ask for something to be PRESENT: a series, a category, a curve, a filtered-out
row that should be gone. For every requirement of that kind, look for the thing itself before you
answer. If you cannot point at it in the figure or in the code, the verdict is VIOLATED; do not
answer OK for something you did not actually find.

The chart:
"""


_CHART_AUDIT_PROMPT = """A chart was produced from the instructions below. Decide whether it was DRAWN the way the instructions ask.

Instructions:
{instructions}

Requirements to check, one at a time:
{items}

The code the agent ran:
{code}

For each numbered requirement above, answer on its own line in exactly this form:

<n>. OK | <what you see that satisfies it>
<n>. VIOLATED | <what the instructions ask> but <what the figure shows>

Quote what you actually see in the figure: an axis scale, a limit, a colour, the legend entry, a
tick rotation. Answer OK only after checking that requirement against the figure -- never because
the chart looks plausible. Do not report a requirement that is not in the list above.

Some requirements ask for something to be PRESENT: a legend, a marker, a label, an annotation, a
colour, a panel. For every requirement of that kind, search the figure for the thing itself before
you answer. If you cannot point at it, the verdict is VIOLATED. Answering OK for something you did
not actually find -- because the chart looks finished, or because it usually is there -- is the
single most common way this audit goes wrong.

The chart:
"""

#: Readability is the one family whose evidence does not depend on the instruction
#: at all, so no instruction is shown: the question is whether the pixels are
#: legible, not whether they are right. The baseline asked whether the figure was
#: "difficult or impossible to read" and found 0 of the seed set's 39 cases.
_READABILITY_PROMPT = """Here is a chart rendered to a PNG{size_note}. Judge only whether it is physically legible. Whether it follows any instruction is irrelevant and must not affect your answer.

Look for each of these:
1. Text whose colour matches the colour directly behind it, so the characters cannot be made
   out at all: white on a light background, a label drawn in the series colour it sits on.
   Ordinary dark axis labels, tick numbers, titles and legend entries on a light background are
   readable and are not a defect, however thin or small they look.
2. Text that overlaps other text -- tick labels, data labels, annotations.
3. Content cut off by the edge of the image.
4. A data series or line drawn in the same colour as the background, so it is invisible.
5. Text rendered so small that the characters genuinely cannot be made out -- not merely small.
   A chart's default tick labels and axis titles are readable at any normal figure size.

Report every defect you find, one per line, in exactly this form:

DEFECT | <which check number> | <the exact text or element, quoted as it appears> | <where it is>

If nothing is wrong, answer exactly: NONE
Report only defects you can point at in this image. Do not pad the list.

The chart:
"""


# --- shared plumbing --------------------------------------------------------- #

def _error(family: ErrorFamily, evidence: str) -> Error:
    """契约要求 evidence 非空，所以兜底而不是抛异常。"""
    return Error(family=family, evidence=evidence.strip() or f"{family.value} (no evidence)")


def _collect(violations: dict[ErrorFamily, list[str]]) -> list[Error]:
    """一个 family 无论命中多少条违规，都只产出一个 Error，证据拼接。"""
    return [
        _error(family, " | ".join(items))
        for family in ErrorFamily
        if (items := violations.get(family))
    ]


def _figure_part(run: Run) -> dict:
    """The figure as a chat content part.

    The media type comes from the bytes rather than from the filename: an agent
    that writes JPEG data into figure.png is rare but the runner only ever looks
    for that name, and a data URL that disagrees with its payload is a hard error
    rather than a wrong answer.
    """
    data = run.figure.read_bytes()
    with Image.open(io.BytesIO(data)) as image:
        image_format = (image.format or "PNG").upper()
    media_type = {
        "JPG": "image/jpeg",
        "JPEG": "image/jpeg",
    }.get(image_format, f"image/{image_format.lower()}")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{base64.b64encode(data).decode()}"},
    }


def _ask(prompt: str, run: Run, *, with_figure: bool = True, max_tokens: int) -> str:
    """One model call. Deliberately lets exceptions through: a transport failure is
    what the runner's retry is for, and swallowing it here would turn a failed run
    into a silently unjudged one."""
    content: list[dict] = [{"type": "text", "text": prompt}]
    if with_figure:
        content.append(_figure_part(run))
    response = complete([{"role": "user", "content": content}], max_tokens=max_tokens)
    return (response["choices"][0]["message"]["content"] or "").strip()


def _clip(text: str, limit: int) -> str:
    """Keep both ends, leaning on the tail: the last write of the script is the
    one that ran."""
    if len(text) <= limit:
        return text
    head = limit // 3
    return text[:head] + OMISSION + text[-(limit - head):]


#: Commands that plausibly put the script on disk. Everything else in a trajectory
#: is the agent reading, listing or re-running -- noise for a question about arithmetic.
_WRITE_MARKERS = (".py", "EOF", "<<", "tee ")


def _agent_code(run: Run, limit: int = CODE_LIMIT) -> str:
    """The commands the agent ran, favouring the ones that wrote the script.

    A data error is a claim about numbers -- "the fourth panel omits the cubing
    step" -- and the rendered pixels cannot settle it: no one reads the
    arithmetic of ``15 ** x`` off a log axis. The agent's code can, and it is a
    fraction of the trajectory wrapped around it.
    """
    commands: list[str] = []
    for message in run.messages:
        for call in message.get("tool_calls") or []:
            arguments = (call.get("function") or {}).get("arguments")
            if not isinstance(arguments, str):
                continue
            try:
                command = json.loads(arguments).get("command")
            except (ValueError, AttributeError):
                continue
            if isinstance(command, str) and command.strip():
                commands.append(command.strip())
    writes = [command for command in commands if any(m in command for m in _WRITE_MARKERS)]
    text = "\n\n### next command ###\n\n".join(writes or commands)
    return _clip(text, limit) if text else NO_COMMANDS


def _parse_requirements(reply: str) -> list[tuple[ErrorFamily, str]]:
    items: list[tuple[ErrorFamily, str]] = []
    for line in reply.splitlines():
        match = _REQUIREMENT_RE.match(line)
        if not match:
            continue
        requirement = match.group(2).strip(" |:-\t")
        if requirement:
            items.append((ErrorFamily(match.group(1).lower()), requirement))
    return items


def _parse_verdicts(reply: str) -> list[str]:
    """The evidence of every line the model marked violated, and nothing from the rest.

    An unparseable answer yields no violations, which costs recall and never
    correctness -- the same trade the whole file is built on.
    """
    violations = []
    for line in reply.splitlines():
        match = _VERDICT_RE.match(line)
        if not match or match.group(1).upper() not in _VIOLATION_WORDS:
            continue
        evidence = match.group(2).lstrip(" |:-—\t").strip()
        if evidence:
            violations.append(evidence)
    return violations


def _size_note(run: Run) -> str:
    """" at 800x600 pixels", so a claim of "too small" has a scale to be small against."""
    try:
        with Image.open(run.figure) as image:
            width, height = image.size
    except Exception:
        return ""
    return f" at {width}x{height} pixels"


# --- the four judgements ----------------------------------------------------- #

def judge_execution(run: Run) -> list[Error]:
    """Whether the run produced a figure to judge at all.

    Decided in code, not asked: on the seed set a missing or unreadable figure is
    exactly the label, so this is the whole of execution_failure and it is free.
    """
    if run.figure is None:
        return [
            _error(
                ErrorFamily.EXECUTION_FAILURE,
                "the run left no figure.png, so there was nothing to render",
            )
        ]
    try:
        # verify() returns None on success and raises on a broken file; it is not
        # a predicate, and `not verify()` is True for every intact image.
        with Image.open(run.figure) as image:
            image.verify()
    except Exception as error:
        return [
            _error(
                ErrorFamily.EXECUTION_FAILURE,
                f"figure.png exists but does not decode as an image "
                f"({type(error).__name__}), so the run produced no usable figure",
            )
        ]
    return []


def _requirements(run: Run) -> list[tuple[ErrorFamily, str]]:
    """The instruction's requirements, each tagged data or chart.

    A decomposition that comes back unreadable must not cost the run its other
    verdicts, so anything unparseable degrades to the instruction checked as one
    open question per family -- the baseline's shape, and no worse than it.
    """
    reply = _ask(
        _EXTRACT_PROMPT.format(instructions=run.instructions.strip()),
        run,
        with_figure=False,
        max_tokens=EXTRACT_TOKENS,
    )
    items = _parse_requirements(reply)
    if items:
        return items
    return [
        (family, run.instructions.strip())
        for family in (ErrorFamily.WRONG_DATA, ErrorFamily.WRONG_CHART)
    ]


def judge_data_and_chart(run: Run) -> list[Error]:
    """Whether the figure plots the requested data, built the requested way.

    One call per family, each carrying only its own requirements, because the
    data/chart boundary is where a single open question goes wrong: "every wedge
    is grey" is a chart-design violation, while "every wedge has the same radius,
    so the scores are not encoded" is a data one, and a model asked both at once
    answers neither reliably.
    """
    requirements = _requirements(run)
    violations: dict[ErrorFamily, list[str]] = {}
    for family, template in (
        (ErrorFamily.WRONG_DATA, _DATA_AUDIT_PROMPT),
        (ErrorFamily.WRONG_CHART, _CHART_AUDIT_PROMPT),
    ):
        items = [text for kind, text in requirements if kind is family]
        if not items:
            continue
        reply = _ask(
            template.format(
                instructions=run.instructions.strip(),
                items="\n".join(f"{n}. {text}" for n, text in enumerate(items, 1)),
                code=_agent_code(run),
            ),
            run,
            max_tokens=AUDIT_TOKENS,
        )
        if hits := _parse_verdicts(reply):
            violations[family] = hits
    return _collect(violations)


def judge_readability(run: Run) -> list[Error]:
    """Whether the figure can be read.

    Asked as a search for five specific defects rather than as one opinion, and
    without the instruction -- nothing about what was requested changes whether
    text is legible. The figure is sent at full size on purpose: downscaling it to
    save tokens would manufacture the very defect being looked for.
    """
    if run.figure is None:
        return []
    reply = _ask(
        _READABILITY_PROMPT.format(size_note=_size_note(run)),
        run,
        max_tokens=READABILITY_TOKENS,
    )
    defects = []
    for line in reply.splitlines():
        match = _DEFECT_RE.match(line)
        if not match:
            continue
        fields = [field.strip() for field in match.group(1).split("|") if field.strip()]
        if fields:
            defects.append(" -- ".join(fields))
    if not defects:
        return []
    return [_error(ErrorFamily.HARD_TO_READ, " | ".join(defects))]


def validate(run: Run) -> list[Error]:
    """Everything wrong with one run.

    execution_failure short-circuits because the label contract makes it terminal:
    a run with no figure is graded on that alone, and the other three families
    have nothing to look at.
    """
    execution = judge_execution(run)
    if execution:
        return execution
    return judge_data_and_chart(run) + judge_readability(run)
