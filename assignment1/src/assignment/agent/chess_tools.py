"""Chess tool implementations, decoupled from the agent that registers them.

Every function here takes the HTTP client explicitly instead of reading it off
an agent, so the same code can run in the agent process or inside the sandbox
beside the server it talks to.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx

CHESS_PORT = 8000


def _load_object(arguments: str) -> dict:
    """Parse one tool call's JSON arguments, requiring a JSON object."""
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed arguments: {exc}") from exc
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    return args


def _request_state(
    client: httpx.Client, method: str, endpoint: str, **kwargs: Any
) -> dict[str, Any]:
    """Make one chess API request and validate its JSON response."""

    response = client.request(method, endpoint, **kwargs)
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Chess server returned non-JSON ({response.status_code})."
        ) from exc
    if response.status_code >= 400:
        detail = (
            payload.get("detail", payload) if isinstance(payload, dict) else payload
        )
        raise ValueError(str(detail))
    if not isinstance(payload, dict):
        raise RuntimeError("Chess server response must be a JSON object.")
    return payload


def _simulate_move(client: httpx.Client, arguments: str) -> str:
    """New tool: inspect FEN or simulate one ply without changing the game.

    Takes the raw JSON arguments of one tool call and returns the observation
    to send back, so a bad argument or a server error reaches the model as a
    recoverable ``<chess_error>`` instead of ending the run.
    """
    try:
        args = _load_object(arguments)
        fen = args.get("fen")

        if not isinstance(fen, str) or not fen:
            raise ValueError("simulate_move requires a string 'fen'")

        move = args.get("move")
        if move is not None and not isinstance(move, str):
            raise ValueError("simulate_move 'move' must be a string or null")

        body = {"fen": fen}
        if move is not None:
            body["move"] = move

        payload = _request_state(client, "POST", "/api/simulate", json=body)

    except Exception as exc:
        return f"<chess_error>{exc}</chess_error>"

    return json.dumps(payload)


def _play_move(client: httpx.Client, arguments: str) -> str:
    """Existing tool: play one move as White and return the resulting state.

    Takes the raw JSON arguments of one tool call. Returns the new state, or a
    `<chess_error>` observation if the move could not be played.
    """
    try:
        args = _load_object(arguments)
        move = args.get("move")

        if not isinstance(move, str) or not move:
            raise ValueError("play_move requires a string 'move'")

        payload = _request_state(client, "POST", "/api/move", json={"move": move})

    except Exception as exc:
        return f"<chess_error>{exc}</chess_error>"

    return json.dumps(payload)


def _run_python(env: Any, port: int, arguments: str) -> str:
    """New tool: run Python with access to the existing registered tools.

    The snippet runs inside the sandbox, which already has the tool
    implementations and the chess server, so code the model wrote never
    executes in the agent process.
    """
    try:
        args = _load_object(arguments)
        code = args.get("code")

        if not isinstance(code, str) or not code:
            raise ValueError("run_python requires a string 'code'")

        encoded = base64.b64encode(code.encode()).decode()
        result = env.execute(
            command=[
                "python",
                "/opt/assignment/sandbox_python.py",
                str(port),
                encoded,
            ],
            shell=False,
        )

    except Exception as exc:
        return f"<chess_error>{exc}</chess_error>"

    if result.get("returncode") != 0:
        message = (
            result.get("exception_info")
            or result.get("stderr")
            or "sandbox command failed"
        )
        return f"<chess_error>{message}</chess_error>"
    # A successful run always prints one JSON object; hand it back verbatim.
    return result.get("output") or result.get("stdout") or ""


def _invoke_skill(skills: dict[str, dict[str, str]], arguments: str) -> str:
    """Existing tool: load one skill's instructions into the conversation."""
    try:
        args = _load_object(arguments)
        name = args.get("name")

        if not isinstance(name, str) or not name:
            raise ValueError("invoke_skill requires a string 'name'")

        skill = skills.get(name)
        if skill is None:
            raise ValueError(f"unknown skill: {name}")

    except Exception as exc:
        return f"<chess_error>{exc}</chess_error>"

    return skill["content"]


def _game_state(client: httpx.Client, reset: bool = False) -> dict:
    """Read the live game, or start a new one and read the opening position."""

    method, endpoint = ("POST", "/api/reset") if reset else ("GET", "/api/state")
    return _request_state(client, method, endpoint)
