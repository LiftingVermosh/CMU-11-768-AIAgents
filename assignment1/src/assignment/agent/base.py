"""The domain-independent ReAct loop shared by both agents.

Part 1 completes the generic loop here; the two subclasses in this package
supply only their own tools and tool executors.
"""

from __future__ import annotations

from copy import deepcopy
import json
import logging
import math
import os

import yaml

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from assignment.env import Environment
from assignment.agent.tools import INVOKE_SKILL_TOOL

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_COMPACTION_KEEP_RECENT_STEPS = 1
DEFAULT_COMPACTION_MAX_TOKENS = 1_200
MAX_OBSERVATION_CHARS = 10_000

# Sent to the model as the final turn of the compaction request, right after the
# history being compressed. It asks for a concise factual working memory that
# would let a fresh run resume from the summary plus the retained recent step.
COMPACTION_SYSTEM_PROMPT = (
    "Rewrite the task and action history above as a concise working memory that "
    "a fresh run could continue from, given only this summary and the most "
    "recent step still shown. Be factual and concrete. Keep, where present: the "
    "objective and constraints; files read or edited and the commands that "
    "matter; changes made and their concrete results; approaches that failed "
    "and why; tests run and their outcomes; open blockers; and the next action. "
    "Do not copy commands or tool output verbatim; condense them to the facts "
    "needed later. Omit reasoning that no longer matters. Return only the "
    "summary text."
)


class StepLimitError(Exception):
    """Raised when an agent exhausts its model-call budget."""


def format_tool_output(output: dict[str, Any]) -> str:
    """Format a terminal result as a compact, tagged model observation."""

    elements: list[str] = []
    for key in sorted(output):
        value = output[key]
        if isinstance(value, str) and len(value) > MAX_OBSERVATION_CHARS:
            # Leave room for the elision notice so the formatted value itself,
            # not just its retained source slices, stays below the limit.
            retained_at_each_end = 4_900
            omitted = len(value) - (2 * retained_at_each_end)
            value = (
                f"{value[:retained_at_each_end]}\n"
                f"[{omitted} characters elided; read a narrower range]\n"
                f"{value[-retained_at_each_end:]}"
            )
        elements.append(f"<{key}>{value}</{key}>")
    return "\n".join(elements)


def rough_message_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate prompt tokens without a provider-specific tokenizer."""

    serialized = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    return max(1, math.ceil(len(serialized) / 4))


class Agent:
    """Base class for a ReAct agent with pluggable tools."""

    def __init__(
        self,
        environment: Environment,
        model: str | None = None,
        logs_save_path: str | None = None,
        step_limit: int = 100,
        skills_path: str | None = None,
        auto_stop_environment: bool = True,
        compact_threshold_tokens: int | None = None,
        compaction_keep_recent_steps: int = DEFAULT_COMPACTION_KEEP_RECENT_STEPS,
        compaction_max_tokens: int = DEFAULT_COMPACTION_MAX_TOKENS,
    ):
        self.env = environment
        self.model = model or os.environ.get("OPENAI_MODEL")
        if not self.model:
            raise RuntimeError("OPENAI_MODEL is not set.")

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        base_url = os.environ.get("OPENAI_BASE_URL")
        if not base_url:
            raise RuntimeError("OPENAI_BASE_URL is not set.")
        try:
            max_retries = int(os.environ.get("OPENAI_MAX_RETRIES", "5"))
        except ValueError as exc:
            raise RuntimeError("OPENAI_MAX_RETRIES must be an integer.") from exc
        if max_retries < 0:
            raise RuntimeError("OPENAI_MAX_RETRIES must be non-negative.")

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
        )

        self.logs_save_path = logs_save_path
        self.step_limit = step_limit
        self.auto_stop_environment = auto_stop_environment
        if compact_threshold_tokens is not None and compact_threshold_tokens <= 0:
            raise ValueError("compact_threshold_tokens must be positive or None")
        if (
            compaction_keep_recent_steps is not None
            and compaction_keep_recent_steps < 1
        ):
            raise ValueError("compaction_keep_recent_steps must be at least 1")
        if compaction_max_tokens is not None and compaction_max_tokens < 1:
            raise ValueError("compaction_max_tokens must be positive")
        # A None threshold turns compaction off. The other two settings then
        # describe a compaction that never happens, so fall back to the
        # defaults rather than leaving a None for later code to trip over.
        self.compact_threshold_tokens = compact_threshold_tokens
        self.compaction_keep_recent_steps = (
            DEFAULT_COMPACTION_KEEP_RECENT_STEPS
            if compaction_keep_recent_steps is None
            else compaction_keep_recent_steps
        )
        self.compaction_max_tokens = (
            DEFAULT_COMPACTION_MAX_TOKENS
            if compaction_max_tokens is None
            else compaction_max_tokens
        )

        # Each agent supplies its own opening messages: the standing
        # instructions, and the task statement that starts the run.
        self.system_prompt: str = ""
        self.task_prompt: str = ""

        self.api_prompts: list[list[dict[str, Any]]] = []
        self.api_responses: list[dict[str, Any]] = []
        self.compaction_events: list[dict[str, Any]] = []
        self.tools: list[dict[str, Any]] = []
        self.finished = False
        self.steps_taken = 0

        self.skills_path = Path(skills_path) if skills_path is not None else None
        self.skills: dict[str, dict[str, str]] = (
            self.load_skills(self.skills_path) if self.skills_path is not None else {}
        )

        if self.skills:
            self.tools.append(INVOKE_SKILL_TOOL)

        # TODO(1.1.a): Add machinery to maintain agent state as it takes actions
        # and observes the results.
        self.messages: list[dict[str, Any]] = []

    def load_skills(self, skills_path: Path) -> dict[str, dict[str, str]]:
        """Load the skill folders exposed to this agent."""

        # TODO(1.4): Validate ``skills_path``, discover one ``SKILL.md``
        # per child directory, parse its YAML frontmatter (what's between the
        # `---` tags at the head of the file), and return a mapping
        # keyed by the frontmatter ``name``. Each value must contain a concise
        # ``metadata`` string for the model's skill catalog and the complete
        # ``content`` of the skill file for ``invoke_skill``. Reject duplicate
        # names and malformed or missing frontmatter with a clear
        # ``ValueError``.
        if not skills_path.is_dir():
            raise ValueError(f"{skills_path}: is not a dir")

        skills: dict[str, dict[str, str]] = {}

        for child in sorted(skills_path.iterdir()): # 遍历目录
            if not child.is_dir():
                continue

            # find md file
            md_files = [p for p in child.iterdir() if p.name == "SKILL.md"]
            if len(md_files) != 1:
                raise ValueError(f"{child}: expected exactly one SKILL.md")

            # raw text
            text = md_files[0].read_text(encoding="utf-8")
            if not text.startswith("---"):
                raise ValueError(f"{child}: missing YAML frontmatter")

            # Split
            parts = text.split("---", 2)
            if len(parts) < 3:
                raise ValueError(f"{child}: malformed frontmatter")

            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError as exc:
                raise ValueError(f"{child}: bad YAML: {exc}") from exc

            if not isinstance(meta, dict) or not meta.get("name"):
                raise ValueError(f"{child}: frontmatter needs a `name`")

            name = str(meta["name"])

            if name in skills:
                raise ValueError(f"duplicate skill name: {name}")

            skills[name] = {
                "metadata": "\n".join(f"{k}: {v}" for k, v in meta.items()),
                "content": parts[2].strip(),    # 完整正文
            }

        return skills


    def query_language_model(self) -> dict[str, Any]:
        """Send one tool-enabled Chat Completions request and normalize it."""

        messages = self.build_prompt()
        self.api_prompts.append(deepcopy(messages))
        step_number = self.steps_taken + 1
        print(
            f"[agent] step {step_number}/{self.step_limit}: requesting action",
            flush=True,
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                reasoning_effort="medium",
                max_completion_tokens=4096,
            )
        except Exception as exc:
            print(
                f"[agent] step {step_number}: model request failed after retries "
                f"({type(exc).__name__}: {exc})",
                flush=True,
            )
            raise
        self.api_responses.append(response.model_dump(mode="json"))
        self.steps_taken += 1
        message = self.process_response(response)
        tool_names = [
            call.get("function", {}).get("name", "unknown")
            for call in message.get("tool_calls", [])
            if isinstance(call, dict)
        ]
        if tool_names:
            print(
                f"[agent] step {step_number}: tool call(s): {', '.join(tool_names)}",
                flush=True,
            )
        else:
            print(
                f"[agent] step {step_number}: response contained no parsed tool call; "
                "the loop should preserve the response and continue",
                flush=True,
            )
        return message

    def process_response(self, response: Any) -> dict[str, Any]:
        """Return relevant parts of the language model's response."""

        return response.choices[0].message.model_dump(exclude_none=True)

    def build_prompt(self) -> list[dict[str, Any]]:
        # TODO(1.1.a): Construct a sequence of messages that form the language
        # model prompt. This should include standing instructions, task
        # specification, prior interaction including observations, reasoning,
        # and actions from previous turns. Note that this method should be
        # domain-agnostic and construct the prompt in a way that would apply
        # to any of the inheriting domain-specific agents.

        # You want to be careful about which attributes of the class you modify
        # here as they may also be handled by the subclasses.
        messages_head: list[dict[str, Any]] = [
            {
                "role": "system", 
                "content": self.system_prompt
            },
            {
                "role": "user", 
                "content": self.task_prompt
            }
        ]
        return messages_head + self.messages
        

    def estimate_active_prompt_tokens(self) -> int:
        """Estimate the next prompt, calibrated by the provider's latest usage."""

        current_prompt = self.build_prompt()
        rough_current = rough_message_tokens(current_prompt)
        if not self.api_prompts or not self.api_responses:
            return rough_current

        usage = self.api_responses[-1].get("usage") or {}
        actual_previous = usage.get("prompt_tokens")
        if not isinstance(actual_previous, int):
            return rough_current

        rough_previous = rough_message_tokens(self.api_prompts[-1])
        added_since_previous_request = max(0, rough_current - rough_previous)
        return actual_previous + added_since_previous_request

    @property
    def compaction_enabled(self) -> bool:
        """Whether this agent compacts its context at all."""

        return self.compact_threshold_tokens is not None

    def compact_context(self):
        """Replace parts of prompt with model-generated working memory. Changes the
        content that `build_prompt` emits."""

        # TODO(2.1): Prompt the model to compact the context. The system
        # prompt should ask for concise factual working memory and preserve
        # the objective, constraints, files, commands, edits, concrete
        # results, failed approaches, tests, blockers, and next action.
        # Summarize only an old prefix; retain the original system/task
        # messages verbatim and at least the latest complete assistant action
        # with all linked tool observations. The resulting summary should change
        # what `build_prompt` emits, and reduce the length of the prompt.
        
        # 注意到 (这该死的注意力) self.messages 的结构是交替的 —— assistant(可能带 tool_calls) -> 若干个 tool(每个带 tool_call_id) -> 下一个 assistant... 
        # 每个回合从一条 assistant 消息开始，到它带出的 tool 观察结束。
        # NOTE: 所以边界应该放在 assistant 消息上
        assistant_idx = [i for i, m in enumerate(self.messages) if m.get("role") == "assistant"]
        n = len(assistant_idx)
        k = self.compaction_keep_recent_steps          # 要保留的最近回合数
        boundary = assistant_idx[n - k]                # 保留段(后缀)的起点

        old_prefix  = self.messages[:boundary]          # 要交给模型总结的部分
        recent_tail = self.messages[boundary:]          # 原样保留的部分

        compaction_prompt = [
            {"role": "system", "content": self.system_prompt},  # 压缩 Prompt
            {"role": "user",   "content": self.task_prompt},          # 任务文本
        ] + old_prefix + [
            {"role": "user", "content": COMPACTION_SYSTEM_PROMPT}
        ]

        ### Do not modify this section ###
        compaction_response = self.client.chat.completions.create(
            model=self.model,
            messages=compaction_prompt,
            reasoning_effort="medium",
            max_completion_tokens=self.compaction_max_tokens,
        )

        ### 看来我不得不改（奉化口音） ###
        summary = compaction_response.choices[0].message.content

        self.messages = [
            {"role": "user", "content": f"<working_memory>{summary}</working_memory>"},
        ] + recent_tail

        return compaction_prompt, compaction_response.model_dump(mode="json")
        ##################################

    def maybe_compact_context(self) -> bool:
        """Compact before the next action request when the threshold is reached."""

        if not self.compaction_enabled:
            return False

        # Context too short to compact yet
        if self.estimate_active_prompt_tokens() < self.compact_threshold_tokens:
            return False

        prompt_before = deepcopy(self.build_prompt())

        # Not enough steps (each assistant turn corresponds to a step) to force
        # compaction yet
        if (
            len([m for m in prompt_before if m.get("role") == "assistant"])
            <= self.compaction_keep_recent_steps
        ):
            return False

        compaction_prompt, compaction_response = self.compact_context()
        prompt_after = deepcopy(self.build_prompt())
        self.compaction_events.append(
            {
                "step": self.steps_taken,
                "estimated_tokens_before": rough_message_tokens(prompt_before),
                "estimated_tokens_after": rough_message_tokens(prompt_after),
                "active_prompt_before": deepcopy(prompt_before),
                "compaction_prompt": compaction_prompt,
                "compaction_response": compaction_response,
            }
        )
        return True

    def run(self) -> None:
        """Run ReAct steps, always saving the trajectory and stopping Modal."""

        try:
            # TODO(1.2) Run the ReAct loop. Orchestrate the sequence of
            # prompting the language model to produce reasoning and actions,
            # extracting the tool calls produced by the model, and executing
            # the tool calls to obtain the agent's observation for the next
            # step. Ensure you identify when the agent has completed the task
            # by setting `Agent.finished`. If the agent exceeds the
            # `step_limit`, raise `StepLimitError`.
            while not self.finished:
                if self.steps_taken >= self.step_limit:
                    raise StepLimitError

                # TODO(2.2) Call `maybe_compact_context()` before each new action
                # request in your shared loop. It already estimates active tokens
                # and handles the threshold, and tracks compaction events for
                # logging.
                self.maybe_compact_context()    # 视情况压缩上下文

                message = self.query_language_model()   # step_taken + 1 here
                self.messages.append(message)   # 追加最新 Response

                # (可能的) 调用工具
                tools_call = message.get('tool_calls')
                if tools_call:
                    obj = self.execute_tool_calls(tools_call)
                    self.messages.extend(obj)
                else:
                    self.messages.append(
                        {
                            "role": "user",
                            "content": "If you are finished, finish via the appropriate completion tool; otherwise take your next action with a tool call if necessary."
                        }
                    )

        finally:
            # This block is provided infrastructure. Do not modify it: a
            # trajectory is required even when a run fails.
            if self.logs_save_path:
                path = Path(self.logs_save_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "prompts": self.api_prompts,
                            "responses": self.api_responses,
                            "compactions": self.compaction_events,
                        },
                        indent=2,
                    )
                )
            if self.auto_stop_environment:
                stop = getattr(self.env, "stop", None)
                if callable(stop):
                    stop()

    def execute_tool_calls(
        self, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        """Execute domain-specific calls and return linked tool observations."""

        # You do not need to implement anything here. This method is
        # domain-specific and implemented by the relevant subclasses
        raise NotImplementedError
