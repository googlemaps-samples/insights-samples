"""View selection and framing for one target (UC1 houses, UC4 roofs). Pure geometry, no LLM.

* `house_view_pitch_vfov` frames a house vertically from its distance and height, so the base
  and the roof line are both in view (no fixed pitch).
* `house_view_candidates` checks every ground camera of every pano with
  `rosette.best_camera_for_view`, so the chosen view is the widest one without black
  border and the house width fits.
* `rank_house_views` orders candidates by normalised distance + off-axis angle, at most
  `max_per_seq` per drive sequence.
* `triangulate_house` intersects the bearings of the house boxes returned by Gemini and
  anchors the house id on that point, not on the user's input coordinate.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from svi_geo import entities as ent
from svi_geo import geo, rosette
from svi_geo import triangulate as tri

CAM_HEIGHT_M = 2.5
HOUSE_HEIGHT_M = 8.0
HOUSE_WIDTH_M = 14.0
MARGIN_DEG = 2.0
HOUSE_MAX_RMS_M = 3.0  # a facade box centre is not a point; allow a few metres of misfit

CANDIDATE_COLUMNS = [
    "pano_id",
    "seq_id",
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
    """One row per pano with the best camera and view for the house at (lat, lng).

    `cam_k` is None when no camera of that pano can show the whole house (too close, or the
    needed view would include black border). `frames` rows need pano_id, cam_k,
    observation_id, camera_pose and gcs_uri (and seq_id, if known)."""
    rows = []
    for pid, g in frames.groupby("pano_id", sort=True):
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
            "pano_id": pid,
            "seq_id": recs[0].get("seq_id"),
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
    cands: pd.DataFrame, max_per_seq: int = 3, n: int | None = None
) -> pd.DataFrame:
    """Candidates with a camera, ordered by `dist/dist_max + off_axis/off_max` (lower is
    better, ties by pano_id), at most `max_per_seq` per drive sequence, then the first `n`.

    Always returns a DataFrame with the input columns plus `score`, even when empty."""
    cols = list(cands.columns) + (["score"] if "score" not in cands.columns else [])
    ok = cands[cands["cam_k"].notna()].copy()
    if ok.empty:
        return pd.DataFrame(columns=cols)
    d_max = max(float(ok["dist_m"].max()), 1e-9)
    o_max = max(float(ok["off_axis_deg"].max()), 1e-9)
    ok["score"] = ok["dist_m"] / d_max + ok["off_axis_deg"] / o_max
    ok = ok.sort_values(["score", "pano_id"], kind="stable")
    seq = ok["seq_id"].fillna(ok["pano_id"])
    ok = ok[seq.groupby(seq).cumcount() < max_per_seq]
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
    user_latlng: tuple[float, float] | None = None,
    max_rms_m: float = HOUSE_MAX_RMS_M,
    max_range_m: float = 100.0,
) -> tuple[HouseLocation | None, str]:
    """Intersect the box-centre bearings of >= 2 panos; the id hashes the intersection.

    `user_latlng` is accepted for symmetry with the view search but deliberately unused:
    the id depends only on the imagery. Returns (None, "unlocated") with fewer than 2
    distinct panos or when the rays do not intersect cleanly (parallel, behind, misfit)."""
    del user_latlng
    by_pano: dict[str, HouseSighting] = {}
    for s in sightings:
        by_pano.setdefault(s.pano_id, s)
    if len(by_pano) < 2:
        return None, "unlocated"
    first = next(iter(by_pano.values())).camera_pose
    ref = (float(first["latitude"]), float(first["longitude"]), 0.0)
    rays = []
    for s in by_pano.values():
        b = s.view.box_to_bearings(s.box_px)
        origin = rosette.camera_center_enu(s.camera_pose, ref)
        rays.append(tri.Ray(origin, b["az"], b["el"]))
    hit = tri.intersect_rays(rays, max_range_m=max_range_m, max_rms_m=max_rms_m)
    if not hit.ok or hit.point is None:
        return None, "unlocated"
    lat, lng, _ = geo.enu_to_lla(float(hit.point[0]), float(hit.point[1]), 0.0, *ref)
    lat, lng = float(np.asarray(lat)), float(np.asarray(lng))
    return (
        HouseLocation(lat, lng, ent.entity_id_for("HOUSE", lat, lng), len(rays), hit.rms_m),
        "triangulated",
    )


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
    """Up to `n` roof views (one per pano), spread across drive sequences.

    A pano qualifies if one of its ground cameras (`best_camera_for_view`) can render a view
    `roof_width_m` wide with the eave and the ridge in frame and no black border. Views are
    scored by `off_axis/off_max + distance outside ROOF_BAND_M / 10 m`, then taken
    round-robin across sequences in score order."""
    rows = []
    for pid, g in frames.groupby("pano_id", sort=True):
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
                "pano_id": pid,
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
    df = df.sort_values(["score", "pano_id"], kind="stable")
    seq = df["seq_id"].fillna(df["pano_id"])
    df["_round"] = seq.groupby(seq).cumcount()
    df = df.sort_values(["_round", "score", "pano_id"], kind="stable").head(n)
    return df.drop(columns="_round").reset_index(drop=True)[cols]


FOLIAGE_REJECT = 0.5  # reject a view when foliage covers at least this share of the target


def occlusion_screen(
    img: np.ndarray, centre_box: Sequence[float], max_foliage: float = FOLIAGE_REJECT
) -> dict[str, Any]:
    """Foliage and texture shares inside `centre_box` (x0, y0, x1, y1 pixels); `rejected`
    when foliage covers at least `max_foliage` of it (the roof is hidden by trees)."""
    import cv2

    h, w = img.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in centre_box)
    x0, x1 = max(0, x0), min(w, x1)
    y0, y1 = max(0, y0), min(h, y1)
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return {"foliage_frac": math.nan, "texture_frac": math.nan, "rejected": True}
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    foliage = cv2.inRange(hsv, np.array([35, 40, 40]), np.array([85, 255, 255])) > 0
    texture = rosette.textured_mask(crop)
    fol = float(np.mean(foliage))
    return {"foliage_frac": fol, "texture_frac": float(np.mean(texture)),
            "rejected": fol >= max_foliage}  # fmt: skip
