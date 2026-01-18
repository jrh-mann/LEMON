"""CLI entrypoint for tool-based backend."""

from __future__ import annotations

import argparse
from pathlib import Path

from .orchestrator import Orchestrator
from .logging_utils import setup_logging
from .tools import AnalyzeWorkflowTool, PublishLatestAnalysisTool, ToolRegistry


def build_orchestrator() -> Orchestrator:
    repo_root = Path(__file__).parent.parent.parent
    registry = ToolRegistry()
    registry.register(AnalyzeWorkflowTool(repo_root))
    registry.register(PublishLatestAnalysisTool(repo_root))
    return Orchestrator(registry)


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
    orchestrator = build_orchestrator()

    if args.one_shot:
        print(orchestrator.respond(args.one_shot))
        return

    run_repl(orchestrator)


if __name__ == "__main__":
    main()
