"""The judge model, reached through an OpenAI-compatible endpoint.

`complete` takes chat messages and returns the whole response, so a question can
be one turn or several, with or without a figure attached. ASSIGNMENT.md shows
how to put an image in a message.
"""

import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

#: Stable alias exposed by the canonical student/staff validator deployment.
MODEL = os.getenv("VALIDATOR_MODEL", "validator")


def _client() -> OpenAI:
    base_url = os.getenv("VALIDATOR_BASE_URL")
    api_key = os.getenv("VALIDATOR_API_KEY")
    missing = [
        name
        for name, value in {
            "VALIDATOR_BASE_URL": base_url,
            "VALIDATOR_API_KEY": api_key,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"missing {', '.join(missing)}; copy .env.example to .env and fill in your deployment"
        )
    return OpenAI(base_url=base_url, api_key=api_key, timeout=300, max_retries=3)


def complete(messages: list[dict[str, Any]], **generation: Any) -> dict[str, Any]:
    options = {"temperature": 0, **generation}
    response = _client().chat.completions.create(
        model=MODEL,
        messages=messages,  # type: ignore[arg-type] - kept flexible for image parts
        **options,
    )
    return response.model_dump()


def _tokenizer_request(endpoint: str, **body: Any) -> dict[str, Any]:
    # vLLM's tokenizer routes live beside /v1, not inside it. Keep any proxy
    # path prefix and use the same authenticated client as chat completions.
    client = _client()
    root = str(client.base_url).rstrip("/").removesuffix("/v1")
    return client.post(
        f"{root}/{endpoint}", cast_to=dict[str, Any], body={"model": MODEL, **body}
    )


def tokenize(text: str) -> dict[str, Any]:
    """Return token IDs and max_model_len from the deployed vLLM server."""
    return _tokenizer_request("tokenize", prompt=text, add_special_tokens=False)


def detokenize(tokens: list[int]) -> str:
    return _tokenizer_request("detokenize", tokens=tokens)["prompt"]
