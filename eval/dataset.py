"""Dataset: auto-discovers golden solutions and matching images from fixtures/."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


# Golden JSON filename → image filename mapping.
# Keys are the stem after "golden_", values are the image file in fixtures/images/.
_IMAGE_MAP = {
    "diabetes_treatment": "Diabetes Treatment .png",
    "liver_pathology": "Liver Pathology .png",
    "lipid_management": "workflow_test.jpeg",
}


@dataclass(frozen=True)
class Sample:
    """One evaluation instance: an image paired with its golden solution."""

    name: str  # short key e.g. "diabetes_treatment"
    image_path: Path
    golden_path: Path


def _fixtures_dir() -> Path:
    """Return <repo>/fixtures/."""
    return Path(__file__).resolve().parent.parent / "fixtures"


def load_dataset(names: Optional[List[str]] = None) -> List[Sample]:
    """Load evaluation samples from fixtures/.

    Args:
        names: Optional filter — only include samples whose name contains
               one of these strings. E.g. ["diabetes", "liver"].
               If None, loads all available samples.

    Returns:
        List of Sample instances, sorted by name.
    """
    fixtures = _fixtures_dir()
    images_dir = fixtures / "images"
    samples: List[Sample] = []

    for golden_file in sorted(fixtures.glob("golden_*.json")):
        # golden_diabetes_treatment.json → "diabetes_treatment"
        stem = golden_file.stem.removeprefix("golden_")

        image_filename = _IMAGE_MAP.get(stem)
        if image_filename is None:
            continue  # no known image for this golden

        image_path = images_dir / image_filename
        if not image_path.exists():
            continue  # image file missing

        # Apply name filter if provided
        if names is not None:
            if not any(n in stem for n in names):
                continue

        samples.append(Sample(name=stem, image_path=image_path, golden_path=golden_file))

    return samples
