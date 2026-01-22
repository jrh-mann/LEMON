from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from uuid import uuid4


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_to_path() -> None:
    repo_root = _repo_root()
    sys.path.insert(0, str(repo_root / "src"))


def main() -> int:
    _add_repo_to_path()
    from backend.api.auth import (
        get_auth_config,
        hash_password,
        normalize_email,
        validate_email,
        validate_password,
    )
    from backend.storage.auth import AuthStore

    parser = argparse.ArgumentParser(description="Create a local auth user.")
    parser.add_argument("--email", required=True, help="Email address for the user.")
    parser.add_argument("--name", required=True, help="Display name for the user.")
    parser.add_argument("--password", help="Password for the user (will prompt if omitted).")
    parser.add_argument(
        "--db",
        help="Path to auth sqlite db (default: <repo>/.lemon/auth.sqlite).",
    )
    args = parser.parse_args()

    email = normalize_email(args.email)
    email_error = validate_email(email)
    if email_error:
        print(f"Error: {email_error}", file=sys.stderr)
        return 1

    password = args.password or getpass.getpass("Password: ")
    auth_config = get_auth_config()
    password_errors = list(validate_password(password, auth_config))
    if password_errors:
        print(f"Error: {password_errors[0]}", file=sys.stderr)
        return 1

    db_path = Path(args.db) if args.db else _repo_root() / ".lemon" / "auth.sqlite"
    auth_store = AuthStore(db_path)

    if auth_store.get_user_by_email(email):
        print(f"Error: user already exists for {email}", file=sys.stderr)
        return 1

    user_id = f"user_{uuid4().hex}"
    password_hash = hash_password(password, config=auth_config)
    auth_store.create_user(user_id, email, args.name.strip(), password_hash)
    print(f"Created user {email} in {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
