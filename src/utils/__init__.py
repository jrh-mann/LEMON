"""Utilities for the LEMON project."""

from typing import TYPE_CHECKING

__all__ = [
    "get_anthropic_client",
    "make_request",
    "make_simple_request",
    "generate_green_image",
    "image_to_base64",
    "make_image_request",
    "get_token_stats",
    "WorkflowAgent",
    "TestCaseGenerator",
    "generate_test_cases_from_file",
    "generate_workflow_code",
    "CodeTestHarness",
]

if TYPE_CHECKING:
    from .code_generator import generate_workflow_code
    from .code_test_harness import CodeTestHarness
    from .request_utils import (
        generate_green_image,
        get_anthropic_client,
        get_token_stats,
        image_to_base64,
        make_image_request,
        make_request,
        make_simple_request,
    )
    from .test_case_generator import TestCaseGenerator, generate_test_cases_from_file
    from .workflow_agent import WorkflowAgent


def __getattr__(name: str):
    if name in {
        "get_anthropic_client",
        "make_request",
        "make_simple_request",
        "generate_green_image",
        "image_to_base64",
        "make_image_request",
        "get_token_stats",
    }:
        from . import request_utils

        return getattr(request_utils, name)
    if name in {"TestCaseGenerator", "generate_test_cases_from_file"}:
        from . import test_case_generator

        return getattr(test_case_generator, name)
    if name == "WorkflowAgent":
        from .workflow_agent import WorkflowAgent

        return WorkflowAgent
    if name == "generate_workflow_code":
        from .code_generator import generate_workflow_code

        return generate_workflow_code
    if name == "CodeTestHarness":
        from .code_test_harness import CodeTestHarness

        return CodeTestHarness
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
