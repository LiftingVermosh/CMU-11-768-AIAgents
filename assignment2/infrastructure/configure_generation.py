"""Store generation endpoint settings in the Modal gateway secret."""

from __future__ import annotations

import argparse
import json
import os

import modal
from dotenv import load_dotenv

from workflow.generate import AGENTS

SECRET_NAME = "hw2-generation-endpoints"


def endpoint_registry() -> dict[str, dict[str, str]]:
    api_key = os.getenv("GENERATION_API_KEY")
    missing = [] if api_key else ["GENERATION_API_KEY"]
    registry = {}
    for agent in AGENTS:
        base_url = os.getenv(agent.url_variable)
        if not base_url:
            missing.append(agent.url_variable)
        else:
            registry[agent.model] = {
                "api_base": base_url.rstrip("/"),
                "api_key": api_key or "",
            }
    if missing:
        raise ValueError(f"missing {', '.join(missing)} in .env")
    return registry


def configure() -> None:
    registry = endpoint_registry()
    values = {"GENERATION_ENDPOINTS_JSON": json.dumps(registry, sort_keys=True)}
    existing = {secret.name for secret in modal.Secret.objects.list()}
    if SECRET_NAME in existing:
        modal.Secret.from_name(SECRET_NAME).update(values)
    else:
        modal.Secret.objects.create(SECRET_NAME, values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    load_dotenv()
    try:
        configure()
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"configured Modal secret {SECRET_NAME!r}")


if __name__ == "__main__":
    main()
