"""Tests for multi-file upload with classification-aware analysis.

Covers:
1. save_uploaded_file handles PDF data URL
2. file_to_data_url returns correct media type for PDF
3. _extract_guidance works with PDF document content block
4. analyze_multi runs guidance on guidance files, skips analysis
5. analyze_multi runs analysis on flowchart files, skips guidance
6. analyze_multi runs guidance THEN analysis on mixed files
7. analyze_multi completes ALL guidance before starting ANY analysis
8. analyze_multi sends all flowchart+mixed files in single LLM call
9. analyze_multi injects accumulated guidance into analysis prompt
10. build_system_prompt shows classification instructions for multiple unclassified files
11. build_system_prompt shows "call analyze" for single file
12. Orchestrator passes uploaded_files in session_state to tools
13. Full pipeline: upload 3 files (guidance + flowchart + mixed) -> guidance first -> analysis
"""

import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from src.backend.utils.uploads import save_uploaded_file, decode_data_url
from src.backend.utils.image import file_to_data_url
from src.backend.agents.subagent import Subagent, _build_content_block
from src.backend.agents.orchestrator import Orchestrator
from src.backend.agents.orchestrator_config import build_system_prompt
from src.backend.utils.analysis import normalize_analysis
from src.backend.tools import ToolRegistry
from src.backend.storage.history import HistoryStore


# --- Helpers ---

def _make_pdf_data_url() -> str:
    """Create a minimal PDF data URL for testing."""
    # Minimal valid-ish PDF content (enough for base64 round-trip)
    pdf_bytes = b"%PDF-1.4 test content"
    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    return f"data:application/pdf;base64,{b64}"


def _make_image_data_url() -> str:
    """Create a minimal PNG data URL for testing."""
    # Minimal 1x1 PNG
    png_bytes = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
        b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
        b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
        b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _make_subagent() -> Subagent:
    """Create a Subagent with a mocked history store."""
    history = MagicMock(spec=HistoryStore)
    return Subagent(history)


def _make_classified_files(tmpdir: str) -> list[dict]:
    """Create test files on disk and return classified file dicts."""
    # Create a fake image file
    img_path = Path(tmpdir) / "flowchart.png"
    img_path.write_bytes(b"fake png content")

    # Create a fake PDF file
    pdf_path = Path(tmpdir) / "guidance.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 guidance content")

    # Create another image for mixed
    mixed_path = Path(tmpdir) / "mixed.png"
    mixed_path.write_bytes(b"fake mixed png content")

    return [
        {
            "id": "file_1",
            "name": "guidance.pdf",
            "abs_path": str(pdf_path),
            "file_type": "pdf",
            "purpose": "guidance",
        },
        {
            "id": "file_2",
            "name": "flowchart.png",
            "abs_path": str(img_path),
            "file_type": "image",
            "purpose": "flowchart",
        },
        {
            "id": "file_3",
            "name": "mixed.png",
            "abs_path": str(mixed_path),
            "file_type": "image",
            "purpose": "mixed",
        },
    ]


# --- Test 1: save_uploaded_file handles PDF ---

class TestSaveUploadedFile:
    def test_saves_pdf_and_returns_pdf_type(self):
        """save_uploaded_file should decode a PDF data URL and return file_type='pdf'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_url = _make_pdf_data_url()
            rel_path, file_type = save_uploaded_file(data_url, repo_root=Path(tmpdir))
            assert file_type == "pdf"
            assert rel_path.endswith(".pdf")
            # Verify file exists
            full_path = Path(tmpdir) / ".lemon" / rel_path
            assert full_path.exists()

    def test_saves_image_and_returns_image_type(self):
        """save_uploaded_file should decode an image data URL and return file_type='image'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_url = _make_image_data_url()
            rel_path, file_type = save_uploaded_file(data_url, repo_root=Path(tmpdir))
            assert file_type == "image"
            assert rel_path.endswith(".png")


# --- Test 2: file_to_data_url for PDF ---

class TestFileToDataUrl:
    def test_pdf_returns_correct_media_type(self):
        """file_to_data_url should return application/pdf media type for .pdf files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "test.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test")
            result = file_to_data_url(pdf_path)
            assert result.startswith("data:application/pdf;base64,")

    def test_png_returns_image_media_type(self):
        """file_to_data_url should return image/png for .png files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_path = Path(tmpdir) / "test.png"
            png_path.write_bytes(b"fake png")
            result = file_to_data_url(png_path)
            assert result.startswith("data:image/png;base64,")


# --- Test 3: _extract_guidance with PDF ---

class TestExtractGuidancePdf:
    def test_pdf_uses_document_content_block(self):
        """_extract_guidance should use a 'document' content block for PDF data URLs."""
        subagent = _make_subagent()
        pdf_data_url = _make_pdf_data_url()
        llm_response = json.dumps([{"text": "Legend: circles = decisions", "location": "page 1", "category": "legend"}])

        with patch("src.backend.agents.subagent.call_llm", return_value=llm_response) as mock_llm:
            result = subagent._extract_guidance(data_url=pdf_data_url)

        assert len(result) == 1
        assert result[0]["text"] == "Legend: circles = decisions"
        # Verify the content block type was 'document' (not image_url)
        call_args = mock_llm.call_args[0][0]  # messages argument
        user_content = call_args[1]["content"]
        file_block = user_content[1]
        assert file_block["type"] == "document"
        assert file_block["source"]["media_type"] == "application/pdf"


# --- Test 4-9: analyze_multi ---

class TestAnalyzeMulti:
    """Tests for the two-phase multi-file analysis."""

    def _mock_analysis_response(self) -> str:
        """Return a valid analysis JSON string."""
        return json.dumps({
            "inputs": [{"id": "input_age_int", "name": "age", "type": "int", "description": "Patient age"}],
            "outputs": [{"name": "risk_level", "description": "Risk classification"}],
            "tree": {"start": {"id": "start", "type": "start", "label": "Start", "children": []}},
            "doubts": [],
        })

    def test_guidance_only_files_skip_analysis(self):
        """When all files are guidance, analysis phase should not run."""
        subagent = _make_subagent()
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "guide.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 guide")
            classified = [{
                "id": "f1", "name": "guide.pdf",
                "abs_path": str(pdf_path), "file_type": "pdf", "purpose": "guidance",
            }]

            guidance_response = json.dumps([{"text": "note1", "location": "p1", "category": "note"}])
            with patch("src.backend.agents.subagent.call_llm", return_value=guidance_response) as mock_llm:
                result = subagent.analyze_multi(
                    classified_files=classified, session_id="test_session"
                )

            # Only guidance extraction should have been called, not the full analysis
            # Result should have guidance but empty tree
            assert result["guidance"] == [{"text": "note1", "location": "p1", "category": "note"}]
            assert result["tree"] == {}
            assert result["variables"] == []

    def test_flowchart_only_files_skip_guidance(self):
        """When all files are flowchart, guidance phase should be skipped."""
        subagent = _make_subagent()
        with tempfile.TemporaryDirectory() as tmpdir:
            img_path = Path(tmpdir) / "flow.png"
            img_path.write_bytes(b"fake png")
            classified = [{
                "id": "f1", "name": "flow.png",
                "abs_path": str(img_path), "file_type": "image", "purpose": "flowchart",
            }]

            analysis_response = self._mock_analysis_response()
            # call_llm will only be called for analysis (via call_llm or call_llm_stream), not guidance
            with patch("src.backend.agents.subagent.call_llm", return_value=analysis_response):
                result = subagent.analyze_multi(
                    classified_files=classified, session_id="test_session"
                )

            # Should have analysis results, no guidance
            assert result["guidance"] == []
            assert len(result["variables"]) == 1

    def test_mixed_files_run_guidance_then_analysis(self):
        """Mixed files should first run guidance extraction, then be included in analysis."""
        subagent = _make_subagent()
        with tempfile.TemporaryDirectory() as tmpdir:
            mixed_path = Path(tmpdir) / "mixed.png"
            mixed_path.write_bytes(b"fake mixed png")
            classified = [{
                "id": "f1", "name": "mixed.png",
                "abs_path": str(mixed_path), "file_type": "image", "purpose": "mixed",
            }]

            guidance_response = json.dumps([{"text": "note from mixed", "location": "top", "category": "note"}])
            analysis_response = self._mock_analysis_response()

            call_count = {"n": 0}
            def mock_llm(messages, **kwargs):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return guidance_response  # First call: guidance extraction
                return analysis_response  # Second call: analysis

            with patch("src.backend.agents.subagent.call_llm", side_effect=mock_llm):
                result = subagent.analyze_multi(
                    classified_files=classified, session_id="test_session"
                )

            # Should have both guidance and analysis results
            assert len(result["guidance"]) == 1
            assert result["guidance"][0]["text"] == "note from mixed"
            assert len(result["variables"]) == 1

    def test_all_guidance_completes_before_analysis(self):
        """ALL guidance extraction must complete before ANY analysis begins."""
        subagent = _make_subagent()
        call_order: list[str] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            files = _make_classified_files(tmpdir)
            # files[0] = guidance, files[1] = flowchart, files[2] = mixed

            guidance_response = json.dumps([{"text": "note", "location": "p1", "category": "note"}])
            analysis_response = self._mock_analysis_response()

            def mock_llm(messages, **kwargs):
                tag = kwargs.get("request_tag", "")
                if tag == "extract_guidance":
                    call_order.append("guidance")
                    return guidance_response
                call_order.append("analysis")
                return analysis_response

            with patch("src.backend.agents.subagent.call_llm", side_effect=mock_llm):
                result = subagent.analyze_multi(
                    classified_files=files, session_id="test_session"
                )

            # Guidance calls must all come before any analysis call
            # files[0]=guidance and files[2]=mixed both get guidance extraction
            guidance_calls = [c for c in call_order if c == "guidance"]
            analysis_calls = [c for c in call_order if c == "analysis"]
            assert len(guidance_calls) == 2  # guidance + mixed
            assert len(analysis_calls) == 1  # single analysis call
            # All guidance calls before analysis
            last_guidance_idx = max(i for i, c in enumerate(call_order) if c == "guidance")
            first_analysis_idx = min(i for i, c in enumerate(call_order) if c == "analysis")
            assert last_guidance_idx < first_analysis_idx

    def test_single_llm_call_for_all_analysis_files(self):
        """All flowchart + mixed files should be sent in a single LLM call."""
        subagent = _make_subagent()

        with tempfile.TemporaryDirectory() as tmpdir:
            files = _make_classified_files(tmpdir)

            guidance_response = json.dumps([])
            analysis_response = self._mock_analysis_response()

            analysis_calls: list = []

            def mock_llm(messages, **kwargs):
                tag = kwargs.get("request_tag", "")
                if tag == "extract_guidance":
                    return guidance_response
                # Capture the analysis call messages
                analysis_calls.append(messages)
                return analysis_response

            with patch("src.backend.agents.subagent.call_llm", side_effect=mock_llm):
                subagent.analyze_multi(
                    classified_files=files, session_id="test_session"
                )

            # Only one analysis LLM call
            assert len(analysis_calls) == 1
            # User content should have text block + one block per analysis file (flowchart + mixed = 2)
            user_content = analysis_calls[0][1]["content"]
            # First block is text, rest are file blocks
            file_blocks = [b for b in user_content if b.get("type") != "text"]
            assert len(file_blocks) == 2  # flowchart.png + mixed.png

    def test_guidance_injected_into_analysis_prompt(self):
        """Accumulated guidance should be included in the analysis prompt."""
        subagent = _make_subagent()

        with tempfile.TemporaryDirectory() as tmpdir:
            files = _make_classified_files(tmpdir)

            guidance_items = [
                {"text": "HbA1c threshold", "location": "top-right", "category": "definition"},
                {"text": "BMI cutoff 30", "location": "bottom", "category": "constraint"},
            ]
            guidance_response = json.dumps(guidance_items)
            analysis_response = self._mock_analysis_response()

            analysis_prompts: list[str] = []

            def mock_llm(messages, **kwargs):
                tag = kwargs.get("request_tag", "")
                if tag == "extract_guidance":
                    return guidance_response
                # Capture the text content of the analysis prompt
                for msg in messages:
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                analysis_prompts.append(block["text"])
                return analysis_response

            with patch("src.backend.agents.subagent.call_llm", side_effect=mock_llm):
                subagent.analyze_multi(
                    classified_files=files, session_id="test_session"
                )

            # The analysis prompt should mention the guidance items
            prompt_text = " ".join(analysis_prompts)
            assert "HbA1c threshold" in prompt_text
            assert "BMI cutoff 30" in prompt_text
            assert "Guidance Notes" in prompt_text


# --- Test 10-11: build_system_prompt ---

class TestBuildSystemPromptFiles:
    def test_multiple_unclassified_files_shows_classification_instructions(self):
        """Multiple unclassified files should trigger classification instructions."""
        files = [
            {"id": "f1", "name": "image1.png", "purpose": "unclassified"},
            {"id": "f2", "name": "doc.pdf", "purpose": "unclassified"},
        ]
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=files,
            allow_tools=True,
        )
        assert "BEFORE analyzing" in prompt
        assert "classify each file" in prompt
        assert "image1.png" in prompt
        assert "doc.pdf" in prompt

    def test_single_file_shows_simple_instruction(self):
        """Single file should show simple 'file uploaded' instruction."""
        files = [{"id": "f1", "name": "diagram.png", "purpose": "unclassified"}]
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=files,
            allow_tools=True,
        )
        assert "uploaded a file" in prompt
        # Should NOT ask for classification
        assert "classify each file" not in prompt

    def test_no_files_no_file_section(self):
        """No files should not add any file-related instructions."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
        )
        assert "uploaded" not in prompt.split("## CRITICAL")[0]  # Only in the base prompt

    def test_classified_files_shows_ready_to_analyze(self):
        """All classified files should trigger 'ready to analyze' instruction."""
        files = [
            {"id": "f1", "name": "flow.png", "purpose": "flowchart"},
            {"id": "f2", "name": "guide.pdf", "purpose": "guidance"},
        ]
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=files,
            allow_tools=True,
        )
        assert "classified" in prompt
        assert "Call analyze_workflow" in prompt


# --- Test 12: Orchestrator passes uploaded_files in session_state ---

class TestOrchestratorUploadedFiles:
    def test_uploaded_files_in_session_state(self):
        """Orchestrator.run_tool should include uploaded_files in session_state."""
        registry = ToolRegistry()
        # Register a simple mock tool
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.execute.return_value = {"success": True}
        registry.register(mock_tool)

        orch = Orchestrator(registry)
        orch.uploaded_files = [
            {"id": "f1", "name": "test.png", "path": "uploads/test.png", "file_type": "image", "purpose": "flowchart"}
        ]

        orch.run_tool("test_tool", {"arg": "value"})

        # Verify session_state was passed with uploaded_files
        call_kwargs = mock_tool.execute.call_args
        session_state = call_kwargs.kwargs.get("session_state") or call_kwargs[1].get("session_state", {})
        assert "uploaded_files" in session_state
        assert len(session_state["uploaded_files"]) == 1
        assert session_state["uploaded_files"][0]["id"] == "f1"


# --- Test 13: Full pipeline ---

class TestFullPipeline:
    """Integration test: 3 files -> classify -> guidance first -> analysis."""

    def test_three_files_guidance_then_analysis(self):
        """Upload guidance + flowchart + mixed -> guidance extracted first -> single analysis call."""
        subagent = _make_subagent()
        call_sequence: list[str] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            files = _make_classified_files(tmpdir)

            guidance_response = json.dumps([{"text": "threshold is 7.5", "location": "top", "category": "definition"}])
            analysis_response = json.dumps({
                "inputs": [{"id": "input_hba1c_float", "name": "hba1c", "type": "float", "description": "HbA1c level"}],
                "outputs": [{"name": "treatment", "description": "Treatment recommendation"}],
                "tree": {"start": {"id": "start", "type": "start", "label": "Start", "children": []}},
                "doubts": [],
            })

            def mock_llm(messages, **kwargs):
                tag = kwargs.get("request_tag", "")
                if tag == "extract_guidance":
                    call_sequence.append("guidance")
                    return guidance_response
                call_sequence.append("analysis")
                return analysis_response

            with patch("src.backend.agents.subagent.call_llm", side_effect=mock_llm):
                result = subagent.analyze_multi(
                    classified_files=files, session_id="pipeline_test"
                )

            # Verify ordering: all guidance before analysis
            assert call_sequence == ["guidance", "guidance", "analysis"]

            # Verify result structure
            assert "variables" in result
            assert "outputs" in result
            assert "tree" in result
            assert "guidance" in result
            assert "reasoning" in result

            # Guidance from both guidance + mixed files (2 calls returning 1 item each)
            assert len(result["guidance"]) == 2

            # Analysis results present
            assert len(result["variables"]) == 1
            assert result["variables"][0]["name"] == "hba1c"


# --- _build_content_block helper ---

class TestBuildContentBlock:
    def test_pdf_data_url_returns_document_block(self):
        """PDF data URL should produce a 'document' content block."""
        block = _build_content_block(_make_pdf_data_url())
        assert block["type"] == "document"
        assert block["source"]["media_type"] == "application/pdf"
        assert block["source"]["type"] == "base64"

    def test_image_data_url_returns_image_block(self):
        """Image data URL should produce an 'image_url' content block."""
        block = _build_content_block(_make_image_data_url())
        assert block["type"] == "image_url"
        assert "url" in block["image_url"]


# --- decode_data_url PDF support ---

class TestDecodeDataUrlPdf:
    def test_pdf_media_type_returns_pdf_ext(self):
        """decode_data_url should return ext='pdf' for application/pdf."""
        data_url = _make_pdf_data_url()
        raw_bytes, ext = decode_data_url(data_url)
        assert ext == "pdf"
        assert raw_bytes == base64.b64decode(data_url.split(",")[1])
