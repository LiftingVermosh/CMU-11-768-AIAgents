"""The Part 1 coding agent: fix a software issue and submit a git patch."""

from __future__ import annotations

import json
from typing import Any

from assignment.agent.base import (
    DEFAULT_COMPACTION_KEEP_RECENT_STEPS,
    DEFAULT_COMPACTION_MAX_TOKENS,
    Agent,
    format_tool_output,
)
from assignment.agent.tools import EXECUTE_TOOL, SEND_MESSAGE_TOOL
from assignment.env import Environment

class CodeAgent(Agent):
    """An agent that fixes a software issue and submits a git patch."""

    def __init__(
        self,
        task: str,
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
        super().__init__(
            environment=environment,
            model=model,
            logs_save_path=logs_save_path,
            step_limit=step_limit,
            skills_path=skills_path,
            auto_stop_environment=auto_stop_environment,
            compact_threshold_tokens=compact_threshold_tokens,
            compaction_keep_recent_steps=compaction_keep_recent_steps,
            compaction_max_tokens=compaction_max_tokens,
        )
        self.task = task
        self.submitted_patch = ""

        # TODO(Part 1.3): Make the `execute` and `send_message` tools available
        # to the agent.
        self.tools.append(EXECUTE_TOOL)
        self.tools.append(SEND_MESSAGE_TOOL)

        # TODO(1.1.b): Construct the system prompt and task_prompt. These
        # should be usable by the `Agent.build_prompt` method.
        env = self.env
        self.system_prompt = (
            "You are an autonomous coding agent working inside a disposable sandbox.\n"
            "Use the `execute` tool to run shell commands: reproduce the problem, locate its cause, make a minimal fix, and verify it. Prefer small output; read large files with `head`, `tail`, or `sed -n` ranges.\n"
            "<system_information>\n"
            f"{json.dumps({'machine': env.machine, 'release': env.release, 'system': env.system, 'version': env.version}, indent=2)}\n"
            "</system_information>\n"
        )
        self.task_prompt = (
            f"Work in {getattr(env, 'cwd', '/testbed')}. Fix the issue described "
            f"below so the project's tests pass.\n\n{self.task}"
        )

        # TODO(1.4): If any skills are available to the agent, make their
        # descriptions/metadata available to the agent in the prompt.
        if self.skills:
            catalog = "\n".join(s["metadata"] for s in self.skills.values())
            self.system_prompt += (
                "\n\nReusable skills are available. Call `invoke_skill` with a skill's name to load its instructions, and follow them in place of your default approach."
                f"\n\n<skills>\n{catalog}\n</skills>\n"
            )

    def execute_tool_calls(
        self, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        """Execute ``execute`` and ``send_message`` calls in the code sandbox."""

        observations = []
        for cur_call in tool_calls:
            # [注]: 这里模型返回的工具调用是 OpenAI 的 *invocation*：
            #     {
            #       "id": ..., 
            #       "type": "function",
            #       "function": {"name": ..., "arguments": <json string>}
            #     }
            # - `id` 会被映射到对应的 observation 中，作为 `tool_call_id`。
            # - `function.arguments` 才是由模型选择的 JSON *字符串*，而不是
            # 我们在请求时的 `parameters` 结构
            call_id = cur_call.get("id")
            call_name = cur_call.get("function", {}).get("name")
            try:
                args = json.loads(
                    cur_call.get("function", {}).get("arguments") or "{}"
                )
                if not isinstance(args, dict):
                    raise ValueError("arguments must be an object")
            except (json.JSONDecodeError, ValueError) as exc:
                observations.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": f"<error>malformed arguments: {exc}</error>",
                    }
                )
                # Nothing valid to execute; skip to the next call so a bad
                # call never falls through to the handlers below.
                continue

            if call_name == "execute":
                command = args.get("command")
                if not isinstance(command, (str, list)):
                    content = (
                        "<error>execute requires a 'command' string or argv list"
                        "</error>"
                    )
                else:
                    result = self.env.execute(
                        command=command,
                        timeout=args.get("timeout"),
                        cwd=args.get("cwd"),
                        env=args.get("env"),
                        shell=args.get("shell"),
                    )
                    # <output>…</output> etc.; truncates past 10,000 chars.
                    content = format_tool_output(result)
            elif call_name == "send_message":
                content = f"<message>{args.get('summary', '')}</message>"
                self.finished = True  # 模型交差,run() 据此正常收尾
            elif call_name == "invoke_skill":
                name = args.get("name")
                skill = self.skills.get(name)
                content = (
                    f"<skill>{skill['content']}</skill>"
                    if skill else f"<error>unknown skill: {name}</error>"
                )
            else:
                # Recoverable observation, never an exception.
                content = f"<error>unknown tool: {call_name}</error>"
            observations.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": content,
                }
            )
        return observations