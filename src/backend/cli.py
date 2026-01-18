"""CLI entrypoint for tool-based backend."""

from __future__ import annotations

import argparse
from pathlib import Path

from .agents.orchestrator import Orchestrator
from .agents.orchestrator_factory import build_orchestrator
from .utils.logging import setup_logging


def run_repl(orchestrator: Orchestrator) -> None:
    print("LEMON backend agent (type 'exit' to quit)")
    while True:
        try:
            user_message = input("> ").strip()
        except EOFError:
            break
        if not user_message:
            continue
        if user_message.lower() in {"exit", "quit"}:
            break
        response = orchestrator.respond(user_message)
        print(response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backend CLI")
    parser.add_argument("--one-shot", help="Run a single prompt and exit")
    args = parser.parse_args()

    setup_logging()
    repo_root = Path(__file__).parent.parent.parent
    orchestrator = build_orchestrator(repo_root)

    if args.one_shot:
        print(orchestrator.respond(args.one_shot))
        return

    run_repl(orchestrator)


if __name__ == "__main__":
    main()
