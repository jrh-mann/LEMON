"""Test script to verify workflow persistence functionality."""

import sys
from pathlib import Path
import tempfile
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from backend.storage.workflows import WorkflowStore

def test_workflow_persistence():
    """Test basic workflow CRUD operations."""
    print("Testing workflow persistence...")

    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        # Initialize store
        print(f"\n1. Initializing WorkflowStore at {db_path}")
        store = WorkflowStore(db_path)
        print("   [OK] Store initialized successfully")

        # Create test workflow
        print("\n2. Creating test workflow")
        test_user_id = "test_user_123"
        test_workflow_id = "wf_test_001"

        store.create_workflow(
            workflow_id=test_workflow_id,
            user_id=test_user_id,
            name="Test Workflow",
            description="A test workflow for persistence",
            domain="Healthcare",
            tags=["test", "demo"],
            nodes=[
                {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0, "color": "teal"},
                {"id": "n2", "type": "end", "label": "End", "x": 200, "y": 0, "color": "rose"}
            ],
            edges=[
                {"id": "e1", "from": "n1", "to": "n2", "label": ""}
            ],
            inputs=[
                {"id": "inp1", "name": "age", "type": "int", "description": "Patient age"}
            ],
            outputs=[
                {"name": "result", "description": "Diagnosis result"}
            ],
            tree={"start": {"id": "n1", "type": "start"}},
            doubts=[],
            validation_score=5,
            validation_count=10,
            is_validated=False,
        )
        print("   [OK] Workflow created successfully")

        # Retrieve workflow
        print("\n3. Retrieving workflow")
        workflow = store.get_workflow(test_workflow_id, test_user_id)
        assert workflow is not None, "Workflow not found"
        assert workflow.name == "Test Workflow"
        assert workflow.domain == "Healthcare"
        assert len(workflow.tags) == 2
        assert len(workflow.nodes) == 2
        assert len(workflow.edges) == 1
        assert len(workflow.inputs) == 1
        print(f"   [OK] Retrieved workflow: {workflow.name}")
        print(f"     - Domain: {workflow.domain}")
        print(f"     - Tags: {workflow.tags}")
        print(f"     - Nodes: {len(workflow.nodes)}")
        print(f"     - Edges: {len(workflow.edges)}")

        # List workflows
        print("\n4. Listing workflows")
        workflows, count = store.list_workflows(test_user_id)
        assert count == 1, f"Expected 1 workflow, got {count}"
        assert len(workflows) == 1
        print(f"   [OK] Found {count} workflow(s)")

        # Update workflow
        print("\n5. Updating workflow")
        success = store.update_workflow(
            test_workflow_id,
            test_user_id,
            name="Updated Test Workflow",
            validation_score=8,
        )
        assert success, "Update failed"

        updated = store.get_workflow(test_workflow_id, test_user_id)
        assert updated.name == "Updated Test Workflow"
        assert updated.validation_score == 8
        print("   [OK] Workflow updated successfully")
        print(f"     - New name: {updated.name}")
        print(f"     - New validation score: {updated.validation_score}")

        # Search workflows
        print("\n6. Searching workflows")
        results, count = store.search_workflows(
            test_user_id,
            query="Updated",
            domain="Healthcare",
        )
        assert count == 1, f"Expected 1 result, got {count}"
        print(f"   [OK] Search found {count} result(s)")

        # Get domains
        print("\n7. Getting domains")
        domains = store.get_domains(test_user_id)
        assert "Healthcare" in domains
        print(f"   [OK] Found domains: {domains}")

        # Delete workflow
        print("\n8. Deleting workflow")
        success = store.delete_workflow(test_workflow_id, test_user_id)
        assert success, "Delete failed"

        workflows, count = store.list_workflows(test_user_id)
        assert count == 0, f"Expected 0 workflows after delete, got {count}"
        print("   [OK] Workflow deleted successfully")

        print("\n[SUCCESS] All tests passed!")
        return True

    except Exception as e:
        print(f"\n[FAIL] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Cleanup
        if db_path.exists():
            db_path.unlink()
            print(f"\nCleaned up test database: {db_path}")

if __name__ == "__main__":
    success = test_workflow_persistence()
    sys.exit(0 if success else 1)
