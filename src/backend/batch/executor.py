"""Batch workflow executor for running a workflow against multiple patients.

Takes a workflow record and a list of patient rows (each with emis_number and
input_values), executes the workflow for each patient, and returns results.
Patients with missing or invalid inputs are marked SKIPPED rather than crashing
the batch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..execution.interpreter import TreeInterpreter

if TYPE_CHECKING:
    from ..storage.workflows import WorkflowRecord, WorkflowStore

logger = logging.getLogger(__name__)


@dataclass
class BatchResultRow:
    """Result of executing a workflow for a single patient."""
    emis_number: str
    success: bool
    output: Optional[str]
    path: Optional[List[str]]
    status: str  # "SUCCESS" | "SKIPPED" | "ERROR"
    error: Optional[str]
    missing_variables: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "emis_number": self.emis_number,
            "success": self.success,
            "output": self.output,
            "path": self.path,
            "status": self.status,
            "error": self.error,
            "missing_variables": self.missing_variables,
        }


class BatchExecutor:
    """Executes a workflow against a batch of patient rows.

    Each patient row is a dict with:
      - emis_number: str — patient identifier
      - input_values: dict — mapping from input *names* to values
        e.g. {"Age": 25, "Total Cholesterol": 5.2}

    The executor converts input names to interpreter IDs internally.
    """

    def __init__(
        self,
        workflow: "WorkflowRecord",
        workflow_store: Optional["WorkflowStore"] = None,
        user_id: Optional[str] = None,
    ):
        self.workflow = workflow
        self.workflow_store = workflow_store
        self.user_id = user_id

        # Pre-compute name→id mapping for converting patient inputs
        self.name_to_id: Dict[str, str] = {
            inp["name"]: inp["id"]
            for inp in (workflow.inputs or [])
            if isinstance(inp, dict)
        }

    def execute_batch(
        self, patient_rows: List[Dict[str, Any]]
    ) -> List[BatchResultRow]:
        """Execute the workflow for every patient row.

        Args:
            patient_rows: List of dicts, each with 'emis_number' and 'input_values'.

        Returns:
            List of BatchResultRow — one per patient, in the same order.
        """
        if not self.workflow.tree or "start" not in self.workflow.tree:
            raise ValueError(
                f"Workflow '{self.workflow.name}' has no execution tree. "
                "Save the workflow first to generate a tree."
            )

        results: List[BatchResultRow] = []
        for row in patient_rows:
            emis_number = str(row.get("emis_number", ""))
            raw_inputs = row.get("input_values", {})

            # Convert human-readable names to interpreter IDs
            input_values, missing = self._map_inputs(raw_inputs)

            if missing:
                # Not enough data to run — skip this patient
                results.append(
                    BatchResultRow(
                        emis_number=emis_number,
                        success=False,
                        output=None,
                        path=None,
                        status="SKIPPED",
                        error=f"Missing required variables: {', '.join(missing)}",
                        missing_variables=missing,
                    )
                )
                continue

            # Create a fresh interpreter per patient
            interpreter = TreeInterpreter(
                tree=self.workflow.tree,
                inputs=self.workflow.inputs,
                outputs=self.workflow.outputs,
                workflow_id=self.workflow.id,
                call_stack=[],
                workflow_store=self.workflow_store,
                user_id=self.user_id,
            )

            result = interpreter.execute(input_values)

            if result.success:
                results.append(
                    BatchResultRow(
                        emis_number=emis_number,
                        success=True,
                        output=result.output,
                        path=result.path,
                        status="SUCCESS",
                        error=None,
                        missing_variables=[],
                    )
                )
            else:
                # Interpreter returned an error (bad condition, missing node, etc.)
                results.append(
                    BatchResultRow(
                        emis_number=emis_number,
                        success=False,
                        output=None,
                        path=result.path,
                        status="ERROR",
                        error=result.error,
                        missing_variables=[],
                    )
                )

        return results

    def _map_inputs(
        self, raw_inputs: Dict[str, Any]
    ) -> tuple[Dict[str, Any], List[str]]:
        """Convert input names to interpreter IDs and detect missing variables.

        Args:
            raw_inputs: Dict mapping input *names* (e.g. "Age") to values.

        Returns:
            Tuple of (mapped_values, missing_names).
            mapped_values uses interpreter IDs as keys.
            missing_names lists variable names that are required but absent.
        """
        mapped: Dict[str, Any] = {}
        missing: List[str] = []

        for inp in self.workflow.inputs or []:
            if not isinstance(inp, dict):
                continue
            # Skip subprocess-derived variables — they're injected at runtime
            if inp.get("source") == "subprocess":
                continue

            name = inp.get("name", "")
            inp_id = inp.get("id", "")

            if name in raw_inputs:
                mapped[inp_id] = raw_inputs[name]
            elif inp_id in raw_inputs:
                # Also accept IDs directly
                mapped[inp_id] = raw_inputs[inp_id]
            else:
                missing.append(name)

        return mapped, missing
