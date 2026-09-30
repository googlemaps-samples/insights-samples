import re
from pathlib import Path

import numpy as np
import pytest

from svi_geo import roof, rosette

INTR = rosette.load_intrinsics()
PKG = Path(roof.__file__).resolve().parent


def test_render_roof_view():
    img = np.zeros((INTR.height, INTR.width, 3), dtype=np.uint8)
    pose = {"heading": 0.0, "latitude": 0.0, "longitude": 0.0}
    res, view, black = roof.render_roof_view(img, INTR, pose, 0.0, 1)
    assert res.shape == (900, 1200, 3)
    assert view.width == 1200 and view.height == 900
    assert 0.0 <= black <= 1.0


@pytest.mark.parametrize("off", [0, 10, 20, 30, -30])
@pytest.mark.parametrize("pitch", [0.0, 14.0])
def test_render_roof_view_has_under_one_percent_black(off, pitch):
    cam_k = 1
    pose = {"heading": 60.0, "pitch": 0.0, "roll": 0.0}
    axis = pose["heading"] + INTR.cam_rot_delta_deg[cam_k][0]
    white = np.full((INTR.height, INTR.width, 3), 255, np.uint8)
    out, view, black = roof.render_roof_view(white, INTR, pose, axis + off, cam_k, pitch)
    measured = float(np.mean(out[..., 0] == 0))
    assert measured < 0.01, (off, pitch, view.hfov_deg, measured)
    assert black == pytest.approx(measured, abs=0.005)


def test_no_hardcoded_half_fov_literals_in_package():
    for path in PKG.glob("*.py"):
        text = path.read_text()
        assert not re.search(r"\b(48\.9|34\.9)\b", text), path.name
