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


# ----------------------------------------------------------------------------- validator v2

import warnings  # noqa: E402

from synthetic_scenes import jitter, make_scene  # noqa: E402

TUNE_SEEDS = range(0, 8)
HELD_OUT_SEEDS = range(8, 16)


def _validate(scene, edges, **kw):
    return roof.validate_roof_edges(
        scene.image, edges, scene.valid_mask, horizon_row=scene.horizon_row, **kw
    )


def test_synthetic_scene_is_seeded_and_complete():
    a, b = make_scene(3), make_scene(3)
    assert np.array_equal(a.image, b.image) and a.edges == b.edges
    assert a.image.shape == (900, 1200, 3)
    assert (~a.valid_mask).any()
    assert np.median(a.image[~a.valid_mask]) < 5  # black up to JPEG ringing at the border
    assert {t for t, _ in a.edges} >= {"EAVE", "RAKE"}


@pytest.mark.parametrize("seeds", [TUNE_SEEDS, HELD_OUT_SEEDS], ids=["tune", "held_out"])
def test_accepts_jittered_ground_truth_edges(seeds):
    acc, n = 0, 0
    for s in seeds:
        scene = make_scene(s)
        edges = jitter(scene.edges, np.random.default_rng(100 + s))
        r = _validate(scene, edges, n_random=0)
        acc += len(r.valid_edges)
        n += len(edges)
    assert acc / n >= 0.90, acc / n


@pytest.mark.parametrize("seeds", [TUNE_SEEDS, HELD_OUT_SEEDS], ids=["tune", "held_out"])
def test_random_segments_are_rarely_accepted(seeds):
    rates = []
    for s in seeds:
        scene = make_scene(s)
        rates.append(
            roof.random_line_baseline(
                scene.image, n=200, seed=s, valid_mask=scene.valid_mask,
                horizon_row=scene.horizon_row,
            )
        )  # fmt: skip
    assert float(np.mean(rates)) < 0.05, rates


def test_result_exposes_random_acceptance():
    scene = make_scene(9)
    r = _validate(scene, scene.edges, n_random=200, seed=9)
    assert r.random_acceptance == pytest.approx(
        roof.random_line_baseline(
            scene.image, 200, 9, scene.valid_mask, horizon_row=scene.horizon_row
        )
    )
    assert 0.0 <= r.random_acceptance < 0.05


def test_rejects_segments_along_the_wedge_boundary():
    for s in HELD_OUT_SEEDS:
        scene = make_scene(s)
        (ax, ay), (bx, by), (cx, cy) = scene.wedge.astype(float)
        # the hypotenuse from the vertical side to the bottom side, inset from its ends
        p, q = np.array([bx, by]), np.array([cx, cy])
        seg = [tuple(p + 0.15 * (q - p)), tuple(p + 0.85 * (q - p))]
        r = _validate(scene, [("EAVE", seg)], n_random=0)
        assert not r.valid_edges and r.rejected_edges[0].reason == "outside_valid"


def test_rejects_segments_mostly_over_foliage():
    scene = make_scene(11)
    x, y, rad = scene.foliage_centres[0]
    seg = [(x - 0.8 * rad, y), (x + 0.8 * rad, y)]
    r = _validate(scene, [("RIDGE", seg)], n_random=0)
    assert not r.valid_edges
    assert r.rejected_edges[0].reason in {"foliage", "outside_valid"}


def test_edge_type_is_preserved_on_accepted_and_rejected_edges():
    scene = make_scene(12)
    bogus = ("VALLEY", [(50.0, 50.0), (300.0, 120.0)])  # sky, no edge
    r = _validate(scene, list(scene.edges) + [bogus], n_random=0)
    assert sorted(e.edge_type for e in r.valid_edges) == sorted(t for t, _ in scene.edges)
    assert [e.edge_type for e in r.rejected_edges] == ["VALLEY"]


def test_gradient_support_is_averaged_over_accepted_edges_only():
    scene = make_scene(13)
    bogus = ("RIDGE", [(40.0, 60.0), (400.0, 90.0)])
    r = _validate(scene, list(scene.edges) + [bogus], n_random=0)
    assert r.mean_gradient_support > r.raw_mean_gradient_support
    only_gt = _validate(scene, scene.edges, n_random=0)
    assert r.mean_gradient_support == pytest.approx(only_gt.mean_gradient_support)


def test_snapping_moves_vertices_onto_the_true_edges_within_tolerance():
    tol = 6.0
    for s in HELD_OUT_SEEDS:
        scene = make_scene(s)
        noisy = jitter(scene.edges, np.random.default_rng(200 + s))
        r = _validate(scene, noisy, n_random=0, snap_tol_px=tol)
        by_type = {}
        for (t, pts), (_, gt) in zip(noisy, scene.edges, strict=True):
            by_type.setdefault(t, []).append((pts, gt))
        for e in r.valid_edges:
            same_len = [c for c in by_type[e.edge_type] if len(c[0]) == len(e.points)]
            assert same_len  # vertex count preserved
            pts, gt = min(
                same_len,
                key=lambda c: sum(
                    np.hypot(*np.subtract(a, b)) for a, b in zip(c[0], e.points, strict=True)
                ),
            )
            assert len(e.points) == len(pts)  # vertex count preserved
            for p_snap, p_raw, p_gt in zip(e.points, pts, gt, strict=True):
                assert np.hypot(*np.subtract(p_snap, p_raw)) <= tol + 1e-9
                # snapping does not make it worse than the jitter (a 2 px jitter is <= 2.9 px)
                assert np.hypot(*np.subtract(p_snap, p_gt)) <= 3.5


def test_parallel_consecutive_lines_meet_at_the_midpoint():
    line_a = (np.array([0.0, 0.0]), np.array([1.0, 0.0]))
    line_b = (np.array([0.0, 2.0]), np.array([1.0, 0.0]))  # parallel, 2 px apart
    pts = np.array([[0.0, 0.0], [50.0, 1.0], [100.0, 2.0]])
    out = roof._snap_polyline(pts, [line_a, line_b], tol=6.0)
    assert out[1] == pytest.approx([50.0, 1.0])
    assert out[0] == pytest.approx([0.0, 0.0]) and out[2] == pytest.approx([100.0, 2.0])


def test_foldover_uses_snapped_vertices():
    folded = np.array([[0.0, 0.0], [100.0, 0.0], [5.0, 3.0]])
    assert roof._foldover_count(folded) == (1, 1)
    straight = np.array([[0.0, 0.0], [100.0, 0.0], [200.0, 5.0]])
    assert roof._foldover_count(straight) == (1, 0)


def test_old_name_is_a_deprecated_wrapper():
    scene = make_scene(14)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        r = roof.validate_and_snap_roof_edges(scene.image, [pts for _, pts in scene.edges])
    assert any(issubclass(x.category, DeprecationWarning) for x in w)
    assert isinstance(r, roof.RoofValidationResult)


def test_horizon_row_follows_view_pitch():
    view = rosette.PerspectiveView(0.0, 0.0, 60.0, 1200, 900)
    assert roof.horizon_row_for(view) == pytest.approx(view.cy)
    up = rosette.PerspectiveView(0.0, 14.0, 60.0, 1200, 900)
    assert roof.horizon_row_for(up) > view.cy  # looking up puts the horizon lower


# ----------------------------------------------------------------------------- baselines (F4)
# The validator checks that a straight image edge exists where Gemini drew a roof edge; it
# does not check that the edge belongs to a roof. These tests pin what that means.


def test_random_segments_stay_inside_the_region():
    region = (300.0, 200.0, 800.0, 420.0)  # a roof band: wide and low
    segs = roof.random_segments(900, 1200, n=300, seed=1, region=region)
    assert len(segs) == 300
    pts = np.array([p for s in segs for p in s])
    assert (pts[:, 0] >= region[0]).all() and (pts[:, 0] <= region[2]).all()
    assert (pts[:, 1] >= region[1]).all() and (pts[:, 1] <= region[3]).all()
    lengths = [float(np.hypot(q[0] - p[0], q[1] - p[1])) for p, q in segs]
    assert min(lengths) >= roof.MIN_SEGMENT_PX
    assert segs == roof.random_segments(900, 1200, n=300, seed=1, region=region)


def test_random_segments_region_is_clipped_to_the_image():
    segs = roof.random_segments(900, 1200, n=50, seed=2, region=(-100.0, -50.0, 400.0, 300.0))
    pts = np.array([p for s in segs for p in s])
    assert pts.min() >= 0.0


def _roof_band(scene):
    (ex0, y_eave), (ex1, _) = next(p for t, p in scene.edges if t == "EAVE")
    top = min(y for _, pts in scene.edges for _, y in pts)
    return (ex0, top, ex1, y_eave)


def test_result_baseline_can_be_sampled_in_the_roof_band():
    scene = make_scene(9)
    band = _roof_band(scene)
    r = _validate(scene, scene.edges, n_random=200, seed=9, baseline_region=band)
    assert r.random_acceptance == pytest.approx(
        roof.random_line_baseline(
            scene.image, 200, 9, scene.valid_mask, horizon_row=scene.horizon_row, region=band
        )
    )


def _decoys(scene):
    x0, y_eave, x1, y_base = scene.wall_box
    hz = scene.horizon_row
    return {
        # sky / ground boundary beside the house
        "horizon": [
            [(max(0, x0 - 220), hz), (x0 - 20, hz)],
            [(x1 + 20, hz), (min(1199, x1 + 220), hz)],
        ],
        # wall / ground boundary under the house
        "wall_base": [[(x0 + 20, y_base), (x1 - 20, y_base)]],
        # faint siding courses on the wall (7 % darker lines)
        "siding": [[(x0 + 20, y), (x1 - 20, y)] for y in range(y_eave + 40, y_base - 10, 14)],
    }


def test_straight_non_roof_edges_pass_so_the_validator_is_not_a_roof_classifier():
    acc = {"horizon": [], "wall_base": [], "siding": [], "band_random": []}
    for s in HELD_OUT_SEEDS:
        scene = make_scene(s)
        got = roof.decoy_acceptance(
            scene.image, _decoys(scene), scene.valid_mask, horizon_row=scene.horizon_row
        )
        for k, v in got.items():
            acc[k].append(v)
        acc["band_random"].append(
            roof.random_line_baseline(
                scene.image, 200, s, scene.valid_mask, scene.horizon_row, region=_roof_band(scene)
            )
        )
    mean = {k: float(np.mean(v)) for k, v in acc.items()}
    print("synthetic decoy / roof-band random acceptance:", mean)
    # Measured on held-out seeds 8-15: horizon 0.625, wall base 0.625, siding 0.0, random
    # segments in the roof band 0.001.
    # strong straight boundaries that are not roof edges are accepted ...
    assert mean["horizon"] >= 0.5 and mean["wall_base"] >= 0.5, mean
    # ... faint texture lines and random segments in the roof band are not
    assert mean["siding"] < 0.1 and mean["band_random"] < 0.05, mean


def test_straight_lines_in_a_region_are_lsd_segments_inside_it():
    scene = make_scene(10)
    x0, y_eave, x1, y_base = scene.wall_box
    region = (x0 - 10, y_eave + 5, x1 + 10, y_base + 10)
    lines = roof.straight_lines_in(scene.image, region, min_len_px=40.0)
    assert lines, "the wall base and wall sides are straight edges"
    for (ax, ay), (bx, by) in lines:
        assert region[0] <= min(ax, bx) and max(ax, bx) <= region[2]
        assert region[1] <= min(ay, by) and max(ay, by) <= region[3]
        assert np.hypot(bx - ax, by - ay) >= 40.0


def test_validator_geometric_and_sky_gates_reject_wall_decoys_and_keep_roof_edges():
    for s in HELD_OUT_SEEDS:
        scene = make_scene(s)
        rbox = _roof_band(scene)
        wbox = scene.wall_box
        # True roof edges are kept (>= 90% retention)
        res = roof.validate_roof_edges(
            scene.image,
            scene.edges,
            scene.valid_mask,
            horizon_row=scene.horizon_row,
            roof_box=rbox,
            wall_box=wbox,
            min_sky_contact=0.25,
            n_random=0,
        )
        assert len(res.valid_edges) >= len(scene.edges) - 1
        # Wall base and siding decoys below the eave band are rejected (<= 0.10)
        got = roof.decoy_acceptance(
            scene.image,
            _decoys(scene),
            scene.valid_mask,
            horizon_row=scene.horizon_row,
            roof_box=rbox,
            wall_box=wbox,
            min_sky_contact=0.25,
        )
        assert got["wall_base"] == 0.0
        assert got["siding"] == 0.0
