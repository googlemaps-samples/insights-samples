"""HARD RULE: images reach Gemini only as inline bytes. No URI/file parts anywhere."""

import re
from pathlib import Path

PANORAMIC = Path(__file__).resolve().parents[2]  # street_view_insights/panoramic
FORBIDDEN = [
    re.compile(r"from_uri"),
    re.compile(r"file_uri"),
    re.compile(r"fileData"),
    re.compile(r"file_data\s*="),
    re.compile(r"batches\.create|BatchPredictionJob|batch_prediction", re.I),
]


def _files():
    for sub in ("svi_geo/svi_geo", "svi_geo/scripts", "notebooks", "skills"):
        root = PANORAMIC / sub
        for p in root.rglob("*"):
            if p.suffix in {".py", ".ipynb"} and ".ipynb_checkpoints" not in p.parts:
                yield p


def test_no_uri_parts_in_package_notebooks_or_skill():
    hits = []
    for p in _files():
        text = p.read_text(errors="ignore")
        for rx in FORBIDDEN:
            if rx.search(text):
                hits.append(f"{p.relative_to(PANORAMIC)}: {rx.pattern}")
    assert not hits, "\n".join(hits)


def test_scan_covers_expected_locations():
    names = {p.name for p in _files()}
    assert "gemini_client.py" in names
    assert any(n.endswith(".ipynb") for n in names)
