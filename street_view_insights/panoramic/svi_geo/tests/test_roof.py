import numpy as np

from svi_geo import roof, rosette


def test_render_roof_view():
    img = np.zeros((3648, 5472, 3), dtype=np.uint8)
    intr = rosette.load_intrinsics()
    pose = {"heading": 0.0, "latitude": 0.0, "longitude": 0.0}
    res, view = roof.render_roof_view(img, intr, pose, 0.0, 1)
    assert res.shape == (900, 1200, 3)
