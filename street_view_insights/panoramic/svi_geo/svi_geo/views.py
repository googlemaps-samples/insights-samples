"""View selection and framing for one target (UC1 houses, UC4 roofs). Pure geometry, no LLM.

* `house_view_pitch_vfov` frames a house vertically from its distance and height, so the base
  and the roof line are both in view (no fixed pitch).
* `house_view_candidates` checks every ground camera of every pano with
  `rosette.best_camera_for_view`, so the chosen view is the widest one without black
  border and the house width fits.
* `rank_house_views` orders candidates by normalised distance + off-axis angle, at most
  `max_per_seq` per drive sequence.
* `triangulate_house` intersects the bearings of the house boxes returned by Gemini and
  derives a run-local house id from that point (not from the user's input coordinate);
  `match_house_ids` carries ids from a previous run to houses located within 3 m.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from svi_geo import data, geo, rosette
from svi_geo import entities as ent
from svi_geo import triangulate as tri

CAM_HEIGHT_M = 2.5
HOUSE_HEIGHT_M = 8.0
HOUSE_WIDTH_M = 14.0
MARGIN_DEG = 2.0
HOUSE_MAX_RMS_M = 3.0  # a facade box centre is not a point; allow a few metres of misfit

CANDIDATE_COLUMNS = [
    "capture_id",
    "pano_id",
    "seq_id",
    "capture_time",
    "cam_k",
    "observation_id",
    "gcs_uri",
    "camera_pose",
    "dist_m",
    "bearing",
    "off_axis_deg",
    "pitch",
    "vfov",
    "hfov",
    "max_hfov",
]


def hfov_for_vfov(vfov_deg: float, aspect: float) -> float:
    """Horizontal FOV (deg) of a pinhole view with vertical FOV `vfov_deg`, aspect = w / h."""
    return math.degrees(2 * math.atan(math.tan(math.radians(vfov_deg) / 2) * aspect))


def house_view_pitch_vfov(
    dist_m: float,
    cam_h: float = CAM_HEIGHT_M,
    house_h: float = HOUSE_HEIGHT_M,
    margin_deg: float = MARGIN_DEG,
) -> tuple[float, float]:
    """(pitch, vfov) in degrees whose vertical window holds the house base and roof line,
    each with `margin_deg` to spare, for a house `dist_m` away."""
    base = math.degrees(math.atan(-cam_h / dist_m))
    top = math.degrees(math.atan((house_h - cam_h) / dist_m))
    return (base + top) / 2.0, (top - base) + 2.0 * margin_deg


def _axis_heading(intr: rosette.Intrinsics, pose: Mapping[str, Any], cam_k: int) -> float:
    h = rosette._pose_get(pose, "heading")
    return h + intr.cam_rot_delta_deg.get(int(cam_k), (0.0,))[0]


def house_view_candidates(
    frames: pd.DataFrame,
    lat: float,
    lng: float,
    intr: rosette.Intrinsics,
    aspect: float = 4 / 3,
    house_width_m: float = HOUSE_WIDTH_M,
    house_height_m: float = HOUSE_HEIGHT_M,
    cam_h: float = CAM_HEIGHT_M,
    min_dist_m: float = 5.0,
    max_dist_m: float = 80.0,
    max_hfov: float = 90.0,
) -> pd.DataFrame:
    """One row per rosette (`capture_id`) with the best camera and view for the house at (lat, lng).

    `cam_k` is None when no camera of that rosette can show the whole house (too close, or the
    needed view would include black border). `frames` rows need capture_id (or pano_id), cam_k,
    observation_id, camera_pose and gcs_uri (and seq_id, if known)."""
    frames = data.ensure_capture_id(frames)
    rows = []
    for cid, g in frames.groupby("capture_id", sort=True):
        recs = g.to_dict("records")
        ground = [r for r in recs if rosette.is_ground_camera(int(r["cam_k"]))]
        if not ground:
            continue
        pose0 = ground[0]["camera_pose"]
        dist = float(geo.haversine_m(pose0["latitude"], pose0["longitude"], lat, lng))
        bearing = float(geo.bearing_deg(pose0["latitude"], pose0["longitude"], lat, lng))
        pitch, vfov = house_view_pitch_vfov(max(dist, 1e-3), cam_h, house_height_m)
        need_w = 2 * math.degrees(math.atan(house_width_m / 2 / max(dist, 1e-3)))
        hfov = max(need_w, hfov_for_vfov(vfov, aspect))
        row = {
            "capture_id": cid,
            "pano_id": recs[0].get("pano_id"),
            "seq_id": recs[0].get("seq_id"),
            "capture_time": recs[0].get("capture_time"),
            "cam_k": None,
            "observation_id": None,
            "gcs_uri": None,
            "camera_pose": None,
            "dist_m": dist,
            "bearing": bearing,
            "off_axis_deg": math.nan,
            "pitch": pitch,
            "vfov": vfov,
            "hfov": hfov,
            "max_hfov": math.nan,
        }
        if min_dist_m <= dist <= max_dist_m and hfov <= max_hfov:
            choice = rosette.best_camera_for_view(
                ground, intr, bearing, pitch, aspect, min_hfov=hfov, hfov_cap=max_hfov
            )
            if choice is not None:
                r = choice.row
                row.update(
                    cam_k=int(choice.cam_k),
                    observation_id=r["observation_id"],
                    gcs_uri=r.get("gcs_uri"),
                    camera_pose=r["camera_pose"],
                    off_axis_deg=abs(
                        float(
                            geo.angdiff(
                                _axis_heading(intr, r["camera_pose"], choice.cam_k), bearing
                            )
                        )
                    ),  # fmt: skip
                    vfov=rosette.vfov_for(hfov, aspect),
                    max_hfov=choice.hfov_deg,
                )
        rows.append(row)
    return pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)


def view_for(cand: Mapping[str, Any], width: int = 1024, height: int = 768):
    """The PerspectiveView described by a candidate row."""
    return rosette.PerspectiveView(
        float(cand["bearing"]), float(cand["pitch"]), float(cand["hfov"]), width, height
    )


def rank_house_views(
    cands: pd.DataFrame,
    max_per_seq: int = 3,
    n: int | None = None,
    *,
    diversify_days: bool = False,
    frames: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Candidates with a camera, ordered by `dist/dist_max + off_axis/off_max` (lower is
    better, ties by capture_id), at most `max_per_seq` per drive sequence, then the first `n`.
    When `diversify_days=True` and a `capture_day` column is present (or derived from `frames`),
    interleaves views round-robin across capture days so multi-day passes are represented first.

    Always returns a DataFrame with the input columns plus `score`, even when empty."""
    cols = list(cands.columns) + (["score"] if "score" not in cands.columns else [])
    cands_norm = data.ensure_capture_id(cands)
    ok = cands_norm[cands_norm["cam_k"].notna()].copy()
    if ok.empty:
        return pd.DataFrame(columns=cols)
    d_max = max(float(ok["dist_m"].max()), 1e-9)
    o_max = max(float(ok["off_axis_deg"].max()), 1e-9)
    ok["score"] = ok["dist_m"] / d_max + ok["off_axis_deg"] / o_max
    ok = ok.sort_values(["score", "capture_id"], kind="stable")
    seq = ok["seq_id"].fillna(ok["capture_id"])
    ok = ok[seq.groupby(seq).cumcount() < max_per_seq]
    if diversify_days:
        if "capture_day" not in ok.columns and frames is not None:
            fr_norm = data.ensure_capture_id(frames)
            if "capture_id" in fr_norm.columns:
                if "capture_day" in fr_norm.columns:
                    day_map = fr_norm.drop_duplicates("capture_id").set_index("capture_id")[
                        "capture_day"
                    ]
                    ok = ok.assign(capture_day=ok["capture_id"].map(day_map))
                elif "capture_time" in fr_norm.columns:
                    day_map = (
                        fr_norm.drop_duplicates("capture_id")
                        .assign(
                            _d=pd.to_datetime(fr_norm["capture_time"], utc=True).dt.strftime(
                                "%Y-%m-%d"
                            )
                        )
                        .set_index("capture_id")["_d"]
                    )
                    ok = ok.assign(capture_day=ok["capture_id"].map(day_map))
        if "capture_day" in ok.columns:
            day_key = ok["capture_day"].fillna(ok["capture_id"]).astype(str)
            ok = ok.assign(_day_round=day_key.groupby(day_key).cumcount())
            ok = ok.sort_values(["_day_round", "score", "capture_id"], kind="stable").drop(
                columns=["_day_round"]
            )
    if n is not None:
        ok = ok.head(n)
    return ok.reset_index(drop=True)[cols]


# ----------------------------------------------------------------------------- triangulation


@dataclasses.dataclass(frozen=True)
class HouseSighting:
    """A house box (view pixels x0, y0, x1, y1) in a view rendered from one pano camera."""

    pano_id: str
    camera_pose: Mapping[str, Any]
    view: rosette.PerspectiveView
    box_px: Sequence[float]


@dataclasses.dataclass(frozen=True)
class HouseLocation:
    lat: float
    lng: float
    entity_id: str
    n_views: int
    rms_m: float


def triangulate_house(
    sightings: Sequence[HouseSighting],
    max_rms_m: float = HOUSE_MAX_RMS_M,
    max_range_m: float = 100.0,
    *,
    use_facade_edges: bool = False,
) -> tuple[HouseLocation | None, str]:
    """Intersect the box-centre bearings of >= 2 panos; the id hashes the intersection.

    When `use_facade_edges=True`, intersects the left-edge bearings and right-edge bearings
    across panos as well and takes the footprint midpoint when both edges converge, falling
    back to the centre-ray intersection otherwise."""
    by_pano: dict[str, HouseSighting] = {}
    for s in sightings:
        by_pano.setdefault(s.pano_id, s)
    if len(by_pano) < 2:
        return None, "unlocated"
    first = next(iter(by_pano.values())).camera_pose
    ref = (float(first["latitude"]), float(first["longitude"]), 0.0)
    rays = []
    left_rays = []
    right_rays = []
    for s in by_pano.values():
        b = s.view.box_to_bearings(s.box_px)
        origin = rosette.camera_center_enu(s.camera_pose, ref)
        rays.append(tri.Ray(origin, b["az"], b["el"]))
        if use_facade_edges:
            ymid = 0.5 * (float(s.box_px[1]) + float(s.box_px[3]))
            az_l, el_l = s.view.pixel_to_bearing(float(s.box_px[0]), ymid)
            az_r, el_r = s.view.pixel_to_bearing(float(s.box_px[2]), ymid)
            left_rays.append(tri.Ray(origin, float(az_l), float(el_l)))
            right_rays.append(tri.Ray(origin, float(az_r), float(el_r)))
    eff_max_rms = (
        max(max_rms_m, 0.5 * ent.SIZE_M.get("HOUSE", 10.0)) if use_facade_edges else max_rms_m
    )
    hit = tri.intersect_rays(rays, max_range_m=max_range_m, max_rms_m=eff_max_rms)
    if use_facade_edges:
        hit_l = tri.intersect_rays(left_rays, max_range_m=max_range_m, max_rms_m=eff_max_rms)
        hit_r = tri.intersect_rays(right_rays, max_range_m=max_range_m, max_rms_m=eff_max_rms)
        if hit_l.ok and hit_l.point is not None and hit_r.ok and hit_r.point is not None:
            mid_pt = 0.5 * (hit_l.point + hit_r.point)
            mid_rms = 0.5 * (hit_l.rms_m + hit_r.rms_m)
            if not hit.ok or mid_rms <= hit.rms_m + 1.0:
                hit = dataclasses.replace(hit_l, point=mid_pt, rms_m=mid_rms, ok=True)
    if not hit.ok or hit.point is None:
        return None, "unlocated"
    lat, lng, _ = geo.enu_to_lla(float(hit.point[0]), float(hit.point[1]), 0.0, *ref)
    lat, lng = float(np.asarray(lat)), float(np.asarray(lng))
    return (
        HouseLocation(lat, lng, ent.entity_id_for("HOUSE", lat, lng), len(rays), hit.rms_m),
        "triangulated",
    )


def match_house_ids(
    previous: Sequence[HouseLocation], new: Sequence[HouseLocation], max_m: float = 3.0
) -> list[str]:
    """Ids for `new`, reusing the id of a previous house located within `max_m`.

    Pairs are taken nearest first and each previous id is reused at most once; a new house
    with no previous house within `max_m` keeps its own (run-local) id."""
    pairs = sorted(
        (float(geo.haversine_m(p.lat, p.lng, n.lat, n.lng)), i, j)
        for i, n in enumerate(new)
        for j, p in enumerate(previous)
    )
    ids = [n.entity_id for n in new]
    used_new: set[int] = set()
    used_prev: set[int] = set()
    for d, i, j in pairs:
        if d > max_m:
            break
        if i in used_new or j in used_prev:
            continue
        ids[i] = previous[j].entity_id
        used_new.add(i)
        used_prev.add(j)
    return ids


# ----------------------------------------------------------------------------- roof views (UC4)

ROOF_WIDTH_M = 14.0  # the view must fit about this width of roof
ROOF_EAVE_M = 3.0  # eave height above the ground
ROOF_TOP_M = 10.0  # ridge height above the ground
ROOF_BAND_M = (12.0, 35.0)  # preferred distance band: close enough to resolve edges, far
# enough that the ridge is not foreshortened out of view


def roof_view_pitch_vfov(
    dist_m: float,
    cam_h: float = CAM_HEIGHT_M,
    eave_h: float = ROOF_EAVE_M,
    top_h: float = ROOF_TOP_M,
    margin_deg: float = MARGIN_DEG,
) -> tuple[float, float]:
    """(pitch, vfov) whose vertical window holds the roof from the eave to the ridge."""
    lo = math.degrees(math.atan((eave_h - cam_h) / dist_m))
    hi = math.degrees(math.atan((top_h - cam_h) / dist_m))
    return (lo + hi) / 2.0, (hi - lo) + 2.0 * margin_deg


def rank_roof_views(
    frames: pd.DataFrame,
    lat: float,
    lng: float,
    intr: rosette.Intrinsics,
    n: int = 4,
    aspect: float = 4 / 3,
    roof_width_m: float = ROOF_WIDTH_M,
    max_dist_m: float = 80.0,
    max_hfov: float = 90.0,
) -> pd.DataFrame:
    """Up to `n` roof views (one per rosette `capture_id`), spread across drive sequences.

    A rosette qualifies if one of its ground cameras (`best_camera_for_view`) can render a view
    `roof_width_m` wide with the eave and the ridge in frame and no black border. Views are
    scored by `off_axis/off_max + distance outside ROOF_BAND_M / 10 m`, then taken
    round-robin across sequences in score order."""
    frames = data.ensure_capture_id(frames)
    rows = []
    for cid, g in frames.groupby("capture_id", sort=True):
        ground = [r for r in g.to_dict("records") if rosette.is_ground_camera(int(r["cam_k"]))]
        if not ground:
            continue
        pose0 = ground[0]["camera_pose"]
        dist = float(geo.haversine_m(pose0["latitude"], pose0["longitude"], lat, lng))
        if not 1.0 <= dist <= max_dist_m:
            continue
        bearing = float(geo.bearing_deg(pose0["latitude"], pose0["longitude"], lat, lng))
        pitch, vfov = roof_view_pitch_vfov(dist)
        need_w = 2 * math.degrees(math.atan(roof_width_m / 2 / dist))
        hfov = max(need_w, hfov_for_vfov(vfov, aspect))
        if hfov > max_hfov:
            continue
        choice = rosette.best_camera_for_view(
            ground, intr, bearing, pitch, aspect, min_hfov=hfov, hfov_cap=max_hfov
        )
        if choice is None:
            continue
        r = choice.row
        rows.append(
            {
                "capture_id": cid,
                "pano_id": r.get("pano_id"),
                "seq_id": r.get("seq_id"),
                "cam_k": int(choice.cam_k),
                "observation_id": r["observation_id"],
                "gcs_uri": r.get("gcs_uri"),
                "camera_pose": r["camera_pose"],
                "dist_m": dist,
                "bearing": bearing,
                "off_axis_deg": abs(
                    float(geo.angdiff(_axis_heading(intr, r["camera_pose"], choice.cam_k), bearing))
                ),  # fmt: skip
                "pitch": pitch,
                "vfov": rosette.vfov_for(hfov, aspect),
                "hfov": hfov,
                "max_hfov": choice.hfov_deg,
            }
        )
    cols = CANDIDATE_COLUMNS + ["score"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)
    lo, hi = ROOF_BAND_M
    outside = np.maximum(0.0, np.maximum(lo - df["dist_m"], df["dist_m"] - hi))
    o_max = max(float(df["off_axis_deg"].max()), 1e-9)
    df["score"] = df["off_axis_deg"] / o_max + outside / 10.0
    df = df.sort_values(["score", "capture_id"], kind="stable")
    seq = df["seq_id"].fillna(df["capture_id"])
    df["_round"] = seq.groupby(seq).cumcount()
    df = df.sort_values(["_round", "score", "capture_id"], kind="stable").head(n)
    return df.drop(columns="_round").reset_index(drop=True)[cols]


FOLIAGE_REJECT = 0.5  # reject a view when vegetation covers at least half of the target box
# A pixel is vegetation when its normalised excess-green index ExG = (2G - R - B) / (R + G + B)
# exceeds EXG_VEGETATION and it is textured (local std-dev, `rosette.textured_mask`). ExG is
# brightness-invariant, so it also catches the dark and dull grey-green canopy that a hue /
# saturation range misses (Woebbecke et al. 1995; ExG > 0 separates plants from soil and
# man-made surfaces, and 0.05 leaves a margin for grey roofs and sky, whose ExG is <= ~0).
# The texture term drops flat green paint and sky. Checked, not tuned, on 12 real roof views
# (Lakeland, FL): the 2 clear roofs scored 0.11 and 0.21, the 8 canopy-hidden views 0.61-0.92.
EXG_VEGETATION = 0.05


def vegetation_mask(img: np.ndarray) -> np.ndarray:
    """Boolean mask of textured pixels whose excess-green index exceeds `EXG_VEGETATION`."""
    f = img.astype(np.float32)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    exg = (2 * g - r - b) / (r + g + b + 1e-6)
    return (exg > EXG_VEGETATION) & rosette.textured_mask(img)


def occlusion_screen(
    img: np.ndarray,
    centre_box: Sequence[float],
    max_foliage: float = FOLIAGE_REJECT,
    min_sky_contact: float = 0.0,
) -> dict[str, Any]:
    """Vegetation and texture shares inside `centre_box` (x0, y0, x1, y1 pixels); `rejected`
    when vegetation (`vegetation_mask`) covers at least `max_foliage` of it, or when
    `min_sky_contact > 0` and `cvchecks.sky_contact(img, centre_box)` is below `min_sky_contact`."""
    from svi_geo import cvchecks as cvc

    h, w = img.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in centre_box)
    x0, x1 = max(0, x0), min(w, x1)
    y0, y1 = max(0, y0), min(h, y1)
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return {
            "foliage_frac": math.nan,
            "texture_frac": math.nan,
            "sky_contact": math.nan,
            "rejected": True,
        }
    fol = float(np.mean(vegetation_mask(crop)))
    sc = float(cvc.sky_contact(img, centre_box))
    sky_fail = bool(min_sky_contact > 0.0 and (not math.isfinite(sc) or sc < min_sky_contact))
    return {
        "foliage_frac": fol,
        "texture_frac": float(np.mean(rosette.textured_mask(crop))),
        "sky_contact": sc,
        "rejected": bool(fol >= max_foliage or sky_fail),
    }


def roof_box(row: Mapping[str, Any], view: rosette.PerspectiveView) -> tuple[float, ...]:
    """Pixel box (x0, y0, x1, y1) around the target roof in a `rank_roof_views` view: about
    `ROOF_WIDTH_M` wide at `row['dist_m']`, from the eave (`ROOF_EAVE_M`) up to the ridge
    (`ROOF_TOP_M`) above the ground."""
    d = float(row["dist_m"])
    u, _, _ = view.bearing_to_pixel(row["bearing"], 0.0)
    half_w = view.f * (ROOF_WIDTH_M / 2) / d
    el_eave = math.degrees(math.atan((ROOF_EAVE_M - CAM_HEIGHT_M) / d))
    el_top = math.degrees(math.atan((ROOF_TOP_M - CAM_HEIGHT_M) / d))
    _, v_eave, _ = view.bearing_to_pixel(row["bearing"], el_eave)
    _, v_top, _ = view.bearing_to_pixel(row["bearing"], el_top)
    return (float(u) - half_w, float(v_top), float(u) + half_w, float(v_eave))


SIDING_HEIGHTS_M = (0.8, 1.4, 2.0)  # wall rows below the eave used as siding decoys


def roof_decoys(
    row: Mapping[str, Any], view: rosette.PerspectiveView
) -> dict[str, list[list[tuple[float, float]]]]:
    """Level non-roof lines across the roof box width for `roof.decoy_acceptance`: the
    horizon (camera height), the wall base (ground) and siding rows (`SIDING_HEIGHTS_M`) at
    `row['dist_m']`. None of them is a roof edge; the share that passes the validator shows
    how often it accepts a straight edge that is not a roof."""
    d = float(row["dist_m"])
    x0, _, x1, _ = roof_box(row, view)
    x0, x1 = max(x0, 0.0), min(x1, view.width - 1.0)

    def level(h: float) -> list[tuple[float, float]]:
        el = math.degrees(math.atan((h - CAM_HEIGHT_M) / d))
        _, v, _ = view.bearing_to_pixel(row["bearing"], el)
        return [(x0, float(v)), (x1, float(v))]

    return {
        "horizon": [level(CAM_HEIGHT_M)],
        "wall_base": [level(0.0)],
        "siding": [level(h) for h in SIDING_HEIGHTS_M],
    }


def wall_box(row: Mapping[str, Any], view: rosette.PerspectiveView) -> tuple[float, ...]:
    """Pixel box (x0, y0, x1, y1) of the walls under `roof_box`: same width, from the eave
    row down to the wall base (ground at `row['dist_m']`). Straight lines found here are
    real image edges that are not roof edges (siding, windows, wall base)."""
    x0, _, x1, y_eave = roof_box(row, view)
    el_base = math.degrees(math.atan(-CAM_HEIGHT_M / float(row["dist_m"])))
    _, v_base, _ = view.bearing_to_pixel(row["bearing"], el_base)
    return (x0, y_eave, x1, float(v_base))


def zoom_view(
    row: Mapping[str, Any] | rosette.PerspectiveView,
    box_2d: Sequence[float],
    factor: float = 2.5,
    width: int = 1024,
    height: int = 768,
    min_hfov_deg: float = 12.0,
) -> rosette.PerspectiveView:
    """Return a narrower `PerspectiveView` centred on `box_2d` ([ymin, xmin, ymax, xmax] in 0..1000)
    with `hfov_deg = max(min_hfov_deg, base_hfov / factor)` for geometric re-rendering from the
    full-resolution fisheye frame (never upsampling a low-res crop)."""
    if isinstance(row, rosette.PerspectiveView):
        base = row
    else:
        base_yaw = float(row.get("bearing", row.get("yaw_deg", 0.0)))
        base_pitch = float(row.get("pitch", row.get("pitch_deg", 0.0)))
        base_hfov = float(row.get("hfov", row.get("hfov_deg", 70.0)))
        base = rosette.PerspectiveView(base_yaw, base_pitch, base_hfov, width, height)
    y0, x0, y1, x1 = (float(v) for v in box_2d)
    xc = 0.5 * (x0 + x1) / 1000.0 * base.width
    yc = 0.5 * (y0 + y1) / 1000.0 * base.height
    az_c, el_c = base.pixel_to_bearing(xc, yc)
    new_hfov = max(float(min_hfov_deg), base.hfov_deg / max(1.0, float(factor)))
    return rosette.PerspectiveView(
        yaw_deg=float(az_c),
        pitch_deg=float(el_c),
        hfov_deg=new_hfov,
        width=int(width),
        height=int(height),
    )


def redaction_overlap(
    image: np.ndarray,
    box_px: Sequence[float],
    thresh: int = 8,
    min_area_frac: float = 2e-5,
) -> float:
    """Fraction of pixels inside `box_px` (`x0, y0, x1, y1` in image pixels) that fall inside a
    solid-black privacy redaction blob (`~rosette.privacy_blob_mask`)."""
    h, w = image.shape[:2]
    x0, y0, x1, y1 = (int(round(float(v))) for v in box_px)
    x0, x1 = max(0, min(w, x0)), max(0, min(w, x1))
    y0, y1 = max(0, min(h, y0)), max(0, min(h, y1))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    not_blob = rosette.privacy_blob_mask(image, thresh=thresh, min_area_frac=min_area_frac)
    sub = ~not_blob[y0:y1, x0:x1]
    return float(np.mean(sub)) if sub.size > 0 else 0.0
