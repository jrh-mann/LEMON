"""Deploy LEMON to Azure Web App using service principal credentials.

Replicates what the GitHub Actions workflow does:
1. Build frontend (npm ci + npm run build)
2. Generate requirements.txt for Oryx
3. Package backend + frontend dist into a zip
4. Deploy zip to Azure Web App via Kudu async zip deploy (triggers Oryx build)

Usage:
    python scripts/deploy_azure.py

Requires AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET,
AZURE_SUBSCRIPTION_ID in .env (or environment).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = REPO_ROOT / "src" / "frontend"
APP_NAME = "lemon-backend"
RESOURCE_GROUP = "UCL_25_26"

# Files/dirs to include in the deployment zip (relative to REPO_ROOT)
ZIP_INCLUDES = [
    "src/backend",
    "src/frontend/dist",
    "scripts",
    "run_api.py",
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",  # Generated for Oryx build; not checked in
]


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    """Run a command, stream output, raise on failure."""
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, env=env)
    if result.returncode != 0:
        print(f"  FAILED (exit {result.returncode})")
        sys.exit(1)


def generate_requirements_txt() -> Path:
    """Generate requirements.txt from pyproject.toml for Azure Oryx build.

    Oryx needs requirements.txt to detect the project as Python and install deps.
    We extract the dependency list from pyproject.toml directly.
    """
    print("\n=== Generating requirements.txt ===")
    req_path = REPO_ROOT / "requirements.txt"

    # Use uv to export if available, fall back to manual extraction
    result = subprocess.run(
        ["uv", "pip", "compile", "pyproject.toml", "-o", str(req_path)],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if result.returncode == 0:
        print(f"  Generated via uv pip compile: {req_path}")
    else:
        # Fallback: read dependencies directly from pyproject.toml
        import tomllib
        with open(REPO_ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        deps = data.get("project", {}).get("dependencies", [])
        req_path.write_text("\n".join(deps) + "\n")
        print(f"  Generated from pyproject.toml deps: {len(deps)} packages")

    return req_path


def build_frontend() -> None:
    """Install deps and build the Vite frontend."""
    print("\n=== Building frontend ===")

    # Remove local env override (same as CI)
    env_local = FRONTEND_DIR / ".env.local"
    if env_local.exists():
        print(f"  Removing {env_local}")
        env_local.unlink()

    run(["npm", "ci"], cwd=FRONTEND_DIR)

    # Build with empty VITE_API_URL (same as CI)
    build_env = {**os.environ, "VITE_API_URL": ""}
    run(["npm", "run", "build"], cwd=FRONTEND_DIR, env=build_env)

    dist = FRONTEND_DIR / "dist"
    if not dist.exists():
        print("  ERROR: frontend dist/ not found after build")
        sys.exit(1)
    print(f"  Frontend built: {dist}")


def create_zip(zip_path: Path) -> None:
    """Package the app into a deployment zip."""
    print(f"\n=== Packaging → {zip_path} ===")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for include in ZIP_INCLUDES:
            full = REPO_ROOT / include
            if full.is_file():
                arcname = str(full.relative_to(REPO_ROOT))
                zf.write(full, arcname)
                print(f"  + {arcname}")
            elif full.is_dir():
                count = 0
                for root, _dirs, files in os.walk(full):
                    # Skip directories that should never be deployed
                    root_path = Path(root)
                    if any(skip in root_path.parts for skip in (
                        "__pycache__", "node_modules", ".git", ".venv",
                        ".pytest_cache", ".lemon", "data", "uploads", "runs",
                    )):
                        continue
                    for f in files:
                        # Skip gitignored file types and runtime artifacts
                        if f.endswith((".pyc", ".pyo", ".pyd", ".sqlite", ".db", ".log")) \
                                or f in (".env", ".DS_Store", ".mcp.json", "tokens.json"):
                            continue
                        file_path = root_path / f
                        arcname = str(file_path.relative_to(REPO_ROOT))
                        zf.write(file_path, arcname)
                        count += 1
                print(f"  + {include}/ ({count} files)")
            else:
                print(f"  WARNING: {include} not found, skipping")

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  Zip size: {size_mb:.1f} MB")


def deploy_to_azure(zip_path: Path) -> None:
    """Deploy the zip to Azure Web App using service principal auth."""
    print("\n=== Deploying to Azure ===")

    # Load credentials
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")

    tenant_id = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET")
    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID")

    missing = []
    if not tenant_id: missing.append("AZURE_TENANT_ID")
    if not client_id: missing.append("AZURE_CLIENT_ID")
    if not client_secret: missing.append("AZURE_CLIENT_SECRET")
    if not subscription_id: missing.append("AZURE_SUBSCRIPTION_ID")
    if missing:
        print(f"  ERROR: Missing env vars: {', '.join(missing)}")
        sys.exit(1)

    from azure.identity import ClientSecretCredential
    from azure.mgmt.web import WebSiteManagementClient

    print(f"  Authenticating as service principal...")
    credential = ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )
    client = WebSiteManagementClient(credential, subscription_id)

    # Read zip bytes
    zip_bytes = zip_path.read_bytes()
    print(f"  Deploying {len(zip_bytes) / (1024*1024):.1f} MB to {APP_NAME}...")

    # Get publishing credentials for the app
    creds = client.web_apps.begin_list_publishing_credentials(
        RESOURCE_GROUP, APP_NAME
    ).result()

    # Deploy via Kudu async zip deploy — triggers Oryx remote build
    import requests
    deploy_url = f"https://{APP_NAME}.scm.azurewebsites.net/api/zipdeploy?isAsync=true"
    print(f"  POST {deploy_url}")

    response = requests.post(
        deploy_url,
        data=zip_bytes,
        auth=(creds.publishing_user_name, creds.publishing_password),
        headers={"Content-Type": "application/zip"},
        timeout=300,
    )

    if response.status_code not in (200, 202):
        print(f"  FAILED: HTTP {response.status_code}")
        print(f"  Response: {response.text[:500]}")
        sys.exit(1)

    # Poll deployment status until Oryx build completes
    poll_url = response.headers.get("Location")
    if poll_url:
        print(f"  Deployment accepted (HTTP {response.status_code}). Waiting for Oryx build...")
        auth = (creds.publishing_user_name, creds.publishing_password)
        for i in range(60):  # Up to 10 minutes (60 * 10s)
            time.sleep(10)
            status_resp = requests.get(poll_url, auth=auth, timeout=30)
            if status_resp.status_code == 200:
                body = status_resp.json()
                progress = body.get("progress", "")
                if progress:
                    print(f"  ... {progress}")
                status = body.get("status", 0)
                # Status 4 = success, 3 = failed
                if status == 4:
                    print(f"  Oryx build + deploy complete!")
                    break
                elif status == 3:
                    print(f"  BUILD FAILED: {body.get('status_text', 'unknown error')}")
                    print(f"  Log: {body.get('log_url', 'N/A')}")
                    sys.exit(1)
            elif status_resp.status_code == 202:
                print(f"  ... still building ({(i+1)*10}s)")
            else:
                print(f"  Unexpected poll response: HTTP {status_resp.status_code}")
        else:
            print("  WARNING: Timed out waiting for build (10 min). Check Azure portal.")

    print(f"  App URL: https://{APP_NAME}.azurewebsites.net")


def main() -> None:
    print("=" * 60)
    print("  LEMON Azure Deployment")
    print("=" * 60)

    # 1. Generate requirements.txt for Oryx
    req_path = generate_requirements_txt()

    try:
        # 2. Build frontend
        build_frontend()

        # 3. Package zip
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "backend.zip"
            create_zip(zip_path)

            # 4. Deploy (async — triggers Oryx build)
            deploy_to_azure(zip_path)
    finally:
        # Clean up generated requirements.txt (not checked in)
        if req_path.exists():
            req_path.unlink()
            print("  Cleaned up generated requirements.txt")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
