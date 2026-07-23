from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / ".env.example"
ENV_PATH = ROOT / ".env"


def _replace_setting(text: str, name: str, value: str) -> str:
    prefix = f"{name}="
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{prefix}{value}"
            return "\n".join(lines) + "\n"
    raise RuntimeError(f"{name} is missing from .env.example")


def build_env(example: str) -> str:
    api_key = secrets.token_urlsafe(48)
    database_password = secrets.token_urlsafe(32)
    principals = {
        api_key: {
            "workspace_id": "demo-workspace",
            "subject": "local-admin",
            "role": "owner",
            "groups": ["*"],
        }
    }

    result = example
    result = _replace_setting(result, "POSTGRES_PASSWORD", database_password)
    result = _replace_setting(
        result,
        "DATABASE_URL",
        f"postgresql+asyncpg://rag:{database_password}@postgres:5432/rag",
    )
    result = _replace_setting(
        result,
        "API_KEYS_JSON",
        json.dumps(principals, separators=(",", ":")),
    )
    result = _replace_setting(result, "BACKEND_API_KEY", api_key)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a secure local .env file")
    parser.add_argument("--force", action="store_true", help="replace an existing .env")
    args = parser.parse_args()

    if ENV_PATH.exists() and not args.force:
        raise SystemExit(".env already exists; use --force only if replacement is intentional")
    if not EXAMPLE_PATH.exists():
        raise SystemExit(".env.example was not found")

    ENV_PATH.write_text(build_env(EXAMPLE_PATH.read_text(encoding="utf-8")), encoding="utf-8")
    try:
        os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass
    print("Created .env with separate random API and PostgreSQL secrets.")


if __name__ == "__main__":
    main()
