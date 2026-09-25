"""Credentialed gateway from the agent scaffold to fixed generation endpoints."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import modal

APP_NAME = "hw2-generation-gateway"
FUNCTION_NAME = "complete"
SECRET_NAME = "hw2-generation-endpoints"

app = modal.App(APP_NAME)
image = modal.Image.debian_slim(python_version="3.12").uv_pip_install(
    "requests==2.32.4"
)
endpoint_secret = modal.Secret.from_name(SECRET_NAME)


def _endpoint(model: str) -> dict[str, str]:
    registry = json.loads(os.getenv("GENERATION_ENDPOINTS_JSON", "{}"))
    try:
        configured = registry[model]
    except KeyError as error:
        raise ValueError(f"no generation endpoint configured for {model!r}") from error
    return {
        "api_base": configured["api_base"],
        "api_key": configured["api_key"],
    }


def _qwen_tool_fallback(
    response: dict[str, Any], tools: list[dict[str, Any]]
) -> dict[str, Any]:
    """Normalize Qwen tool JSON that some vLLM templates leave in content."""
    if not tools or not response.get("model", "").startswith(
        "Qwen/Qwen2.5-Coder-"
    ):
        return response
    allowed = {
        tool["function"]["name"]: tool["function"]
        for tool in tools
        if tool.get("type") == "function" and "function" in tool
    }
    for choice in response.get("choices", []):
        message = choice.get("message", {})
        if message.get("tool_calls") or not isinstance(message.get("content"), str):
            continue
        content = message["content"].strip()
        candidates = [
            match.group(1).strip()
            for match in re.finditer(
                r"<(?:tools|tool_call)>\s*(.*?)\s*</(?:tools|tool_call)>",
                content,
                flags=re.DOTALL,
            )
        ]
        candidates.extend(
            match.group(1).strip()
            for match in re.finditer(
                r"```(?:json)?\s*(.*?)\s*```", content, flags=re.DOTALL
            )
        )
        if not candidates:
            candidates = [content]

        parsed_calls: list[dict[str, Any]] = []
        for candidate in candidates:
            try:
                decoded = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            items = decoded if isinstance(decoded, list) else [decoded]
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                arguments = item.get("arguments")
                if name is None and len(allowed) == 1:
                    name = next(iter(allowed))
                    arguments = item
                if name not in allowed or not isinstance(arguments, (dict, str)):
                    continue
                if isinstance(arguments, str):
                    try:
                        json.loads(arguments)
                    except json.JSONDecodeError:
                        continue
                    encoded_arguments = arguments
                else:
                    encoded_arguments = json.dumps(arguments)
                parsed_calls.append(
                    {
                        "id": f"call_qwen_fallback_{len(parsed_calls)}",
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": encoded_arguments,
                        },
                    }
                )
        if parsed_calls:
            message["tool_calls"] = parsed_calls
            message["content"] = None
            choice["finish_reason"] = "tool_calls"
    return response


@app.function(image=image, secrets=[endpoint_secret], timeout=10 * 60)
def complete(request: dict[str, Any]) -> dict[str, Any]:
    """Forward one OpenAI-compatible completion without exposing credentials."""
    import requests

    endpoint = _endpoint(request["model"])
    base = endpoint["api_base"].rstrip("/")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    payload = {
        "model": request["model"],
        "messages": request["messages"],
        "tools": request.get("tools", []),
        **request.get("generation", {}),
    }
    headers = {"Authorization": f"Bearer {endpoint['api_key']}"}

    response = None
    for attempt in range(6):
        response = requests.post(url, json=payload, headers=headers, timeout=300)
        if response.status_code not in {429, 502, 503, 504}:
            break
        time.sleep(min(30, 2**attempt))
    assert response is not None
    response.raise_for_status()
    return _qwen_tool_fallback(response.json(), payload["tools"])
