import os
from pathlib import Path

import requests


def load_env() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def main() -> None:
    load_env()
    url = os.environ.get("AZURE_OPENAI_ENDPOINT") or os.environ.get("ENDPOINT")
    deployment = (
        os.environ.get("DEPLOYMENT_NAME")
        or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        or os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
    )
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION") or "2024-12-01-preview"

    if not url or not deployment:
        raise SystemExit("Missing AZURE_OPENAI_ENDPOINT/ENDPOINT or DEPLOYMENT_NAME.")

    if "/openai/" not in url:
        url = url.rstrip("/") + f"/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

    headers = {
        "api-key": os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get("API_KEY"),
        "Content-Type": "application/json",
    }
    if not headers["api-key"]:
        raise SystemExit("Missing AZURE_OPENAI_API_KEY/API_KEY.")

    payload = {
        "messages": [{"role": "user", "content": "hello"}],
        "max_completion_tokens": 128,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    print(resp.status_code)
    print(resp.text[:500])


if __name__ == "__main__":
    main()
