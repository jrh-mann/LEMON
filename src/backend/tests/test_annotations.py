"""Tests for annotation save/load and prompt formatting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from ..utils.uploads import save_annotations, load_annotations, _annotations_path_for
from ..agents.subagent import _format_annotations


# ─── Fixtures ────────────────────────────────────────────

@pytest.fixture
def tmp_lemon(tmp_path: Path) -> Path:
    """Create a minimal .lemon structure with an image."""
    data_dir = tmp_path / ".lemon"
    uploads = data_dir / "uploads"
    uploads.mkdir(parents=True)
    # Create a tiny dummy image
    img = uploads / "test_image.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    return tmp_path


@pytest.fixture
def sample_annotations() -> List[Dict[str, Any]]:
    return [
        {"type": "label", "dotX": 120, "dotY": 45, "text": "Check BMI > 30"},
        {"type": "label", "dotX": 300, "dotY": 200, "text": "Start node"},
    ]


# ─── save/load roundtrip ────────────────────────────────

class TestAnnotationPersistence:
    """Test that annotations survive a save → load roundtrip."""

    def test_save_and_load_roundtrip(
        self, tmp_lemon: Path, sample_annotations: List[Dict[str, Any]]
    ):
        rel = "uploads/test_image.png"
        save_annotations(rel, sample_annotations, repo_root=tmp_lemon)
        loaded = load_annotations(Path(rel), repo_root=tmp_lemon)
        assert loaded == sample_annotations

    def test_sidecar_filename(self, tmp_lemon: Path):
        img = tmp_lemon / "lemon_data" / "uploads" / "test_image.png"
        ann_path = _annotations_path_for(img)
        assert ann_path.name == "test_image.png.annotations.json"

    def test_load_returns_empty_when_no_file(self, tmp_lemon: Path):
        loaded = load_annotations(Path("uploads/test_image.png"), repo_root=tmp_lemon)
        assert loaded == []

    def test_load_handles_corrupt_json(self, tmp_lemon: Path):
        img = tmp_lemon / ".lemon" / "uploads" / "test_image.png"
        ann_path = _annotations_path_for(img)
        ann_path.write_text("NOT JSON!!!", encoding="utf-8")
        loaded = load_annotations(Path("uploads/test_image.png"), repo_root=tmp_lemon)
        assert loaded == []

    def test_load_handles_non_list_json(self, tmp_lemon: Path):
        img = tmp_lemon / ".lemon" / "uploads" / "test_image.png"
        ann_path = _annotations_path_for(img)
        ann_path.write_text('{"not": "a list"}', encoding="utf-8")
        loaded = load_annotations(Path("uploads/test_image.png"), repo_root=tmp_lemon)
        assert loaded == []

    def test_empty_annotations_creates_file(self, tmp_lemon: Path):
        rel = "uploads/test_image.png"
        save_annotations(rel, [], repo_root=tmp_lemon)
        loaded = load_annotations(Path(rel), repo_root=tmp_lemon)
        assert loaded == []


# ─── prompt formatting ───────────────────────────────────

class TestAnnotationFormatting:
    """Test that _format_annotations produces correct LLM prompt text."""

    def test_empty_returns_empty(self):
        assert _format_annotations([]) == ""

    def test_label_annotation(self):
        result = _format_annotations([
            {"type": "label", "dotX": 300, "dotY": 150, "text": "Check vitals"}
        ])
        assert 'Label at (300, 150): "Check vitals"' in result

    def test_multiple_labels(self):
        result = _format_annotations([
            {"type": "label", "dotX": 100, "dotY": 200, "text": "Start"},
            {"type": "label", "dotX": 400, "dotY": 500, "text": "End"},
        ])
        assert "1." in result
        assert "2." in result
        assert 'Label at (100, 200): "Start"' in result
        assert 'Label at (400, 500): "End"' in result

    def test_numbering(self, sample_annotations: List[Dict[str, Any]]):
        result = _format_annotations(sample_annotations)
        assert "1." in result
        assert "2." in result

    def test_includes_priority_instruction(self, sample_annotations: List[Dict[str, Any]]):
        result = _format_annotations(sample_annotations)
        assert "priority" in result.lower()

    def test_includes_pixel_coordinate_info(self):
        result = _format_annotations([
            {"type": "label", "dotX": 10, "dotY": 20, "text": "Test"}
        ])
        assert "native image pixels" in result.lower()

    def test_unknown_type_fallback(self):
        result = _format_annotations([
            {"type": "unknown_future_type", "data": "something"}
        ])
        assert "Annotation:" in result
