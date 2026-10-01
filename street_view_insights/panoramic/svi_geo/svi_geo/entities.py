"""Multi-view entity deduplication for discrete street assets (pure numpy/scipy/sklearn).

Input: per-pano `Observation`s (a detection turned into a world bearing `Ray` by code: box ->
pixel -> calibrated camera model -> azimuth/elevation). Output: one `Entity` per physical
object with a triangulated location, the observations that support it, and fused attributes.

Algorithm (per class):
1. Ray voting: every pair of rays from different panos is intersected (`intersect_rays` with
   its conditioning/range checks); single-view ground-contact ranges add votes for classes
   whose box bottom touches the ground.
2. DBSCAN over the votes (class-specific eps) gives candidate centres, ranked by support.
3. Greedy acceptance: for each candidate (highest support first) take, per pano, the nearest
   unused ray within the gate; >= 2 panos -> least-squares refine -> accept, consume rays.
   Rays are consumed, so ghost intersections (rays of two different objects) lose their
   support once the real objects are accepted. Voting repeats on the leftovers, which is
   what separates objects closer than eps (e.g. two poles 2 m apart).
4. A per-pano Hungarian pass re-assigns rays to the accepted centres (one ray per centre per
   pano), then centres are re-triangulated.
5. Leftover rays become single-view entities placed at the ground-contact range of their
   box bottom; without a usable ground contact they are reported as `unlocated` (no
   position is invented).
6. Attributes are fused by confidence-weighted vote; `entity_id` is a hash of the class and
   the rounded location, so it is deterministic and independent of input order.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import DBSCAN

from svi_geo import geo
from svi_geo import triangulate as tri

# Per-class matching tolerance (m) for evaluation (pass-to-pass and baseline matching).
EPS_BY_CLASS = {
    "UTILITY_POLE": 3.0,
    "ROAD_SIGN": 3.0,
    "STREET_LIGHT": 3.0,
    "FIRE_HYDRANT": 2.0,
    "STREET_TREE": 4.0,
    "GATE": 3.0,
    "HOUSE": 8.0,
    "BUILDING": 8.0,
}
DEFAULT_EPS = 4.0
# Classes whose box bottom is the ground-contact point (single-view range from elevation).
POST_GROUP = frozenset({"UTILITY_POLE", "ROAD_SIGN", "STREET_LIGHT", "FIRE_HYDRANT"})
GROUND_CONTACT = {
    "UTILITY_POLE",
    "ROAD_SIGN",
    "STREET_LIGHT",
    "FIRE_HYDRANT",
    "STREET_TREE",
    "GATE",
}
# Classes whose (untruncated) box bottom is where the object meets the ground, so a single
# view can be ranged from its elevation. Buildings are included for single-view placement
# only; their rays are not elevation-gated during clustering.
SINGLE_VIEW_RANGE = GROUND_CONTACT | {"HOUSE", "BUILDING"}
MAX_SINGLE_VIEW_RANGE_M = 60.0
# A single-view range r = h / tan(-el) moves by about r^2 / h per radian of box-bottom error:
# with the camera 2.5 m up that is 6 m/deg at 30 m but 19 m/deg at 52 m. A house box bottom
# is a soft edge (lawn, hedges, shadow), so houses and buildings are placed from one view
# only within 30 m; farther ones are reported as unlocated.
MAX_SINGLE_VIEW_RANGE_BY_CLASS = {"HOUSE": 30.0, "BUILDING": 30.0, "STREET_TREE": 35.0}
# Clustering eps (m) per cluster key: post-like classes share the key POST_GROUP. eps is the
# DBSCAN radius for pair votes and the merge distance; it stays below the spacing of
# neighbouring houses (tests/test_entities.py: two houses 20 m apart).
CLUSTER_EPS = {
    "POST_GROUP": 3.0,
    "STREET_TREE": 4.0,
    "GATE": 3.0,
    "HOUSE": 5.0,
    "BUILDING": 5.0,
}
# Max RMS (m) of a triangulation, separate from eps: a house or building is an extended
# object whose box centre moves along the facade with the viewing angle and with partial
# occlusion, so its rays miss a common point by up to about half its width (SIZE_M / 2 + 1 m
# of noise). Point-like classes keep RMS = eps.
MAX_TRIANGULATION_RMS_M = {
    "POST_GROUP": 3.0,
    "STREET_TREE": 4.0,
    "GATE": 3.0,
    "HOUSE": 6.0,
    "BUILDING": 7.0,
}
GHOST_CONF = 0.65  # single-view detections below this confidence near a same-key entity
# Physical extent that widens the angular gate (box reference points move across views).
SIZE_M = {
    "HOUSE": 10.0,
    "BUILDING": 12.0,
    "STREET_TREE": 2.5,
    "ROAD_SIGN": 0.8,
    "GATE": 3.0,
}
DEFAULT_SIZE_M = 0.5
LEFTOVER_GATE = 3.0  # sigma units for attaching leftover rays to triangulated entities
GROUND_SIGMA_M = 0.0  # extra ground-height sigma (m); >0 loosens gating for noisy altitudes


@dataclasses.dataclass(frozen=True)
class Observation:
    obs_id: str
    pano_id: str
    cls: str
    ray: tri.Ray
    confidence: float = 1.0
    el_bottom_deg: float | None = None
    el_top_deg: float | None = None
    attrs: Mapping[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class Entity:
    entity_id: str
    cls: str
    point_enu: np.ndarray
    lat: float
    lng: float
    obs_ids: list[str]
    pano_ids: list[str]
    method: str  # "triangulated" | "single_view_ground_contact" | "unlocated"
    rms_m: float
    confidence: float
    attrs: dict[str, tuple[Any, float]]
    range_m: float = math.nan  # single-view range from the camera (NaN otherwise)

    @property
    def located(self) -> bool:
        return self.method != "unlocated" and math.isfinite(self.lat)

    @property
    def n_panos(self) -> int:
        return len(set(self.pano_ids))


def fuse_attribute(
    votes: Iterable[tuple[Any, float]],
    ignore: Collection[Any] = (),
    *,
    min_agree_views: int = 1,
) -> tuple[Any, float]:
    """Confidence-weighted vote -> (value, share of total weight).

    Values in `ignore` (e.g. {"UNKNOWN"}) do not vote, so they can never outvote a known
    value; if only ignored values were given the result is (None, 0.0).
    When `min_agree_views > 1` and the top-voted value has fewer than `min_agree_views`
    supporting votes, returns `("UNKNOWN", 0.0)`."""
    skip = set(ignore)
    w: dict[Any, float] = defaultdict(float)
    counts: dict[Any, int] = defaultdict(int)
    for v, c in votes:
        if v is not None and v not in skip:
            w[v] += float(c)
            counts[v] += 1
    if not w:
        return None, 0.0
    tot = sum(w.values())
    best = max(sorted(w, key=str), key=lambda k: w[k])
    if min_agree_views > 1 and counts[best] < min_agree_views:
        return "UNKNOWN", 0.0
    return best, w[best] / tot


def entity_id_for(cls: str, lat: float, lng: float, precision_m: float = 2.0) -> str:
    """Deterministic id from class + location snapped to a ~`precision_m` grid. It changes when
    noise moves the point across a grid line, so it is a run-local key, not a cross-run one."""
    q = precision_m / 111_320.0
    key = f"{cls}:{round(lat / q)}:{round(lng / (q / max(0.1, math.cos(math.radians(lat)))))}"
    return f"{cls.lower()}_{hashlib.sha1(key.encode()).hexdigest()[:10]}"


def located_entities(entities: Iterable[Entity]) -> list[Entity]:
    """Entities with a position (triangulated or single-view ground contact)."""
    return [e for e in entities if e.located]


def cluster_key(cls: str) -> str:
    return "POST_GROUP" if cls in POST_GROUP else cls


def _single_view_range(o: Observation, cam_height_m: float) -> float | None:
    """Range from the elevation of an untruncated box bottom, or None (no guess)."""
    if o.cls not in SINGLE_VIEW_RANGE or o.el_bottom_deg is None:
        return None
    r = tri.single_view_range(o.el_bottom_deg, cam_height_m)
    if r is None or r > MAX_SINGLE_VIEW_RANGE_BY_CLASS.get(o.cls, MAX_SINGLE_VIEW_RANGE_M):
        return None
    return r


def _single_view_point(o: Observation, cam_height_m: float) -> np.ndarray | None:
    r = _single_view_range(o, cam_height_m)
    return None if r is None else tri.point_from_range(o.ray, r)


def _check_eps_keys(eps_by_class: Mapping[str, float]) -> None:
    for k in eps_by_class:
        if k in POST_GROUP:
            raise ValueError(
                f"eps_by_class key {k!r}: this class is clustered under the key 'POST_GROUP'"
            )
        if k not in CLUSTER_EPS:
            raise ValueError(
                f"unknown eps_by_class key {k!r}; valid keys are {sorted(CLUSTER_EPS)}"
            )


def _votes(obs: Sequence[Observation], cam_height_m: float, max_range_m: float):
    pts, members = [], []
    for i in range(len(obs)):
        for j in range(i + 1, len(obs)):
            if obs[i].pano_id == obs[j].pano_id:
                continue
            if np.linalg.norm(obs[i].ray.origin[:2] - obs[j].ray.origin[:2]) > 2 * max_range_m:
                continue
            res = tri.intersect_rays(
                [obs[i].ray, obs[j].ray], max_range_m=max_range_m, max_rms_m=1e9
            )
            if res.ok:
                pts.append(res.point)
                members.append((i, j))
    for i, o in enumerate(obs):
        if o.cls in GROUND_CONTACT:
            p = _single_view_point(o, cam_height_m)
            if p is not None:
                pts.append(p)
                members.append((i,))
    return np.array(pts).reshape(-1, 3), members


def ray_cost(
    o: Observation,
    centre: np.ndarray,
    sigma_deg: float,
    max_range_m: float,
    cam_height_m: float = 2.5,
    ground_sigma_m: float = GROUND_SIGMA_M,
) -> float:
    """Angular misfit of `o` w.r.t. `centre`, in units of its (size-inflated) sigma.

    Azimuth always; for GROUND_CONTACT classes also the elevation of the ground-contact point,
    which separates objects that line up in azimuth (two poles 2 m apart seen from far away).
    The expected elevation uses the centre's absolute height (ground under its supporting
    cameras), so observers on streets at a different height are handled physically;
    `ground_sigma_m` absorbs the height error of that ground estimate.
    `cam_height_m` is only used when the centre has no height (NaN).
    """
    v = np.asarray(centre, float) - o.ray.origin
    t = math.hypot(v[0], v[1])
    if t < 0.5 or t > max_range_m or float(v[:2] @ o.ray.dir2d) <= 0:
        return math.inf
    size = SIZE_M.get(o.cls, DEFAULT_SIZE_M)
    sig = math.hypot(sigma_deg, math.degrees(math.atan2(size / 2, t)))
    daz = ((math.degrees(math.atan2(v[0], v[1])) - o.ray.az_deg + 180.0) % 360.0) - 180.0
    if o.cls in GROUND_CONTACT and o.el_bottom_deg is not None:
        dz = v[2] if math.isfinite(v[2]) else -cam_height_m
        del_ = math.degrees(math.atan2(dz, t)) - o.el_bottom_deg
        sig_el = math.hypot(sigma_deg, math.degrees(math.atan2(ground_sigma_m, t)))
        return math.sqrt(((daz / sig) ** 2 + (del_ / sig_el) ** 2) / 2.0)
    return abs(daz / sig)


def _gate_pick(obs, free, centre, gate, sigma_deg, max_range_m, cam_height_m):
    """Per pano, the lowest-cost free ray with cost <= `gate` -> sorted indices."""
    best: dict[str, tuple[float, int]] = {}
    for i in sorted(free):
        c = ray_cost(obs[i], centre, sigma_deg, max_range_m, cam_height_m)
        if c <= gate and (obs[i].pano_id not in best or c < best[obs[i].pano_id][0]):
            best[obs[i].pano_id] = (c, i)
    return sorted(i for _, i in best.values())


def _contact_z(xy: np.ndarray, obs: Sequence[Observation], cam_height_m: float) -> float:
    """Height of a ground-contact point at horizontal position `xy`: the ground under the
    nearest observing camera (its height - `cam_height_m`). Roadside objects stand within a
    few metres of the nearest pano, so this is the local ground even on slopes, whereas the
    median over all observers is metres off when far observers are higher or lower. It does
    not use the rays' elevations, so elevation gating stays an independent check."""
    d = [float(np.hypot(*(np.asarray(xy[:2], float) - o.ray.origin[:2]))) for o in obs]
    return float(obs[int(np.argmin(d))].ray.origin[2]) - cam_height_m


def _refine(obs, idx, max_range_m, max_rms_m, cam_height_m):
    res = tri.intersect_rays(
        [obs[i].ray for i in idx], max_range_m=max_range_m, max_rms_m=max_rms_m, min_angle_deg=3.0
    )
    if res.ok and obs[idx[0]].cls in GROUND_CONTACT:
        p = res.point.copy()
        p[2] = _contact_z(p, [obs[i] for i in idx], cam_height_m)
        res = dataclasses.replace(res, point=p)
    return res


def _ground(centre: np.ndarray, obs: Sequence[Observation], cam_height_m: float) -> np.ndarray:
    """Vote centres of ground-contact classes get the ground height measured by the rays
    that voted for them (see `_contact_z`)."""
    if obs and obs[0].cls in GROUND_CONTACT:
        c = np.array(centre, float)
        c[2] = _contact_z(c, obs, cam_height_m)
        return c
    return centre


def _cluster_class(obs, eps, cam_height_m, max_range_m, sigma_deg, gate=3.0, rounds=3,
                   max_rms=None):  # fmt: skip
    max_rms = eps if max_rms is None else max_rms
    free = set(range(len(obs)))
    accepted: list[tuple[np.ndarray, list[int], float]] = []
    for _ in range(rounds):
        sub = sorted(free)
        if len(sub) < 2:
            break
        pts, members = _votes([obs[i] for i in sub], cam_height_m, max_range_m)
        if not len(pts):
            break
        labels = DBSCAN(eps=eps / 2, min_samples=1).fit(pts[:, :2]).labels_
        cands = []
        for lab in set(labels):
            m = labels == lab
            voters = sorted({sub[k] for mi in np.nonzero(m)[0] for k in members[mi]})
            cands.append((len(voters), int(m.sum()), np.median(pts[m], axis=0), voters))
        cands.sort(key=lambda c: (-c[0], -c[1], tuple(np.round(c[2], 3))))
        new = 0
        for _, _, centre, voters in cands:
            centre = _ground(centre, [obs[i] for i in voters], cam_height_m)
            idx = _gate_pick(obs, free, centre, 2 * gate, sigma_deg, max_range_m, cam_height_m)
            if len({obs[i].pano_id for i in idx}) < 2:
                continue
            res = _refine(obs, idx, max_range_m, max_rms, cam_height_m)
            if not res.ok:
                continue
            # re-gate tightly around the refined point and refine once more
            idx2 = _gate_pick(obs, free, res.point, gate, sigma_deg, max_range_m, cam_height_m)
            if len({obs[i].pano_id for i in idx2}) < 2:
                continue
            res2 = _refine(obs, idx2, max_range_m, max_rms, cam_height_m)
            if not res2.ok:
                continue
            accepted.append((res2.point, idx2, res2.rms_m))
            free -= set(idx2)
            new += 1
        if not new:
            break
    if not accepted:
        return accepted, sorted(free)
    # per-pano Hungarian re-assignment to the accepted centres, then re-triangulate
    centres = [a[0] for a in accepted]
    by_pano: dict[str, list[int]] = defaultdict(list)
    for i in range(len(obs)):
        by_pano[obs[i].pano_id].append(i)
    assign: dict[int, list[int]] = defaultdict(list)
    for _pid, idxs in sorted(by_pano.items()):
        cost = np.array(
            [
                [ray_cost(obs[i], c, sigma_deg, max_range_m, cam_height_m) for c in centres]
                for i in idxs
            ]
        )
        cost = np.where(np.isfinite(cost), cost, 1e6)
        rr, cc = linear_sum_assignment(cost)
        for r, c in zip(rr, cc, strict=True):
            if cost[r, c] <= gate:
                assign[int(c)].append(idxs[r])
    refined = []
    for c, (_pt, idx0, _rms0) in enumerate(accepted):
        idx = sorted(assign.get(c, []))
        if len({obs[i].pano_id for i in idx}) >= 2:
            res = _refine(obs, idx, max_range_m, max_rms, cam_height_m)
            if res.ok:
                refined.append((res.point, idx, res.rms_m))
                continue
        # fall back to the greedy set minus rays the Hungarian pass gave to other centres
        taken = {i for cc, ii in assign.items() if cc != c for i in ii}
        keep = [i for i in idx0 if i not in taken]
        if len({obs[i].pano_id for i in keep}) >= 2:
            res = _refine(obs, keep, max_range_m, max_rms, cam_height_m)
            if res.ok:
                refined.append((res.point, keep, res.rms_m))
        # otherwise the centre is dropped and its rays return to the leftovers
    refined = _merge_split(obs, refined, eps, cam_height_m, max_range_m, sigma_deg, gate, max_rms)
    refined = _dissolve_ghosts(obs, refined, max_rms, cam_height_m, max_range_m, sigma_deg, gate)
    used = {i for _, idx, _ in refined for i in idx}
    return refined, sorted(set(range(len(obs))) - used)


def _dissolve_ghosts(obs, groups, max_rms, cam_height_m, max_range_m, sigma_deg, gate):
    """Remove ghost centres: intersections of rays that belong to different real objects.

    A weakly supported centre is a ghost when all but at most one of its rays also fit a
    better-supported centre (within `gate`, from a pano that centre does not have yet). Those
    rays move to the better centre (which is re-triangulated); the rest become leftovers.
    Weakest centres are examined first; strong centres are never dissolved into weak ones.
    """
    groups = [(p, list(idx), r) for p, idx, r in groups]
    changed = True
    while changed:
        changed = False
        order = sorted(range(len(groups)), key=lambda k: (len(groups[k][1]), k))
        for g in order:
            idx_g = groups[g][1]
            moves: dict[int, int] = {}
            for i in idx_g:
                best = (gate, None)
                for h, (ph, idx_h, _) in enumerate(groups):
                    if h == g or len(idx_h) <= len(idx_g):
                        continue
                    if obs[i].pano_id in {obs[k].pano_id for k in idx_h}:
                        continue
                    c = ray_cost(obs[i], ph, sigma_deg, max_range_m, cam_height_m)
                    if c <= best[0]:
                        best = (c, h)
                if best[1] is not None:
                    moves[i] = best[1]
            if len(moves) < len(idx_g) - 1 or len(moves) < 1:
                continue
            for i, h in moves.items():
                groups[h][1].append(i)
            for h in set(moves.values()):
                idx = sorted(groups[h][1])
                res = _refine(obs, idx, max_range_m, max_rms, cam_height_m)
                groups[h] = (
                    (res.point, idx, res.rms_m) if res.ok else (groups[h][0], idx, groups[h][2])
                )
            del groups[g]
            changed = True
            break
    return groups


def _merge_split(obs, groups, eps, cam_height_m, max_range_m, sigma_deg, gate, max_rms=None):
    max_rms = eps if max_rms is None else max_rms
    """Merge triangulated centres that are one object split across disjoint pano sets.

    With many near-collinear panos, noisy pair votes spread along the viewing direction and
    the greedy pass can accept two centres a few metres apart for one object, each supported
    by a different set of panos. Two distinct objects close together are seen from the same
    panos, so a pair is only merged when its pano sets are disjoint, the joint triangulation
    succeeds, and every ray still fits the merged point within `gate`. Closest pairs first.
    """
    groups = list(groups)
    while True:
        best = None
        for a in range(len(groups)):
            pa = {obs[i].pano_id for i in groups[a][1]}
            for b in range(a + 1, len(groups)):
                d = float(np.linalg.norm(groups[a][0][:2] - groups[b][0][:2]))
                if d > 2 * eps or (best is not None and d >= best[0]):
                    continue
                if pa & {obs[i].pano_id for i in groups[b][1]}:
                    continue
                idx = sorted(groups[a][1] + groups[b][1])
                res = _refine(obs, idx, max_range_m, max_rms, cam_height_m)
                if not res.ok:
                    continue
                costs = [
                    ray_cost(obs[i], res.point, sigma_deg, max_range_m, cam_height_m) for i in idx
                ]
                if max(costs) <= gate:
                    best = (d, a, b, (res.point, idx, res.rms_m))
        if best is None:
            return groups
        _, a, b, merged = best
        groups = [g for k, g in enumerate(groups) if k not in (a, b)] + [merged]


def _refine_house_edges(
    members: Sequence[Observation],
    fallback_pt: np.ndarray,
    fallback_rms: float,
    max_range_m: float,
    max_rms_m: float,
) -> tuple[np.ndarray, float]:
    """Refine a multi-view HOUSE cluster using left/right facade-edge rays when available."""
    left_rays: list[tri.Ray] = []
    right_rays: list[tri.Ray] = []
    for m in members:
        meta = m.ray.meta or {}
        az_l = meta.get("az_left")
        az_r = meta.get("az_right")
        if az_l is not None and az_r is not None:
            left_rays.append(tri.Ray(m.ray.origin, float(az_l), m.ray.el_deg))
            right_rays.append(tri.Ray(m.ray.origin, float(az_r), m.ray.el_deg))
    if len(left_rays) >= 2 and len(right_rays) >= 2:
        eff_rms = max(max_rms_m, 0.5 * SIZE_M.get("HOUSE", 10.0) + 1.5)
        hit_l = tri.intersect_rays(left_rays, max_range_m=max_range_m, max_rms_m=eff_rms)
        hit_r = tri.intersect_rays(right_rays, max_range_m=max_range_m, max_rms_m=eff_rms)
        if hit_l.ok and hit_l.point is not None and hit_r.ok and hit_r.point is not None:
            mid_pt = 0.5 * (hit_l.point + hit_r.point)
            mid_rms = 0.5 * (hit_l.rms_m + hit_r.rms_m)
            return mid_pt, float(mid_rms)
    return fallback_pt, fallback_rms


def cluster(
    observations: Sequence[Observation],
    ref_lla: Sequence[float],
    eps_by_class: Mapping[str, float] | None = None,
    cam_height_m: float = 2.5,
    max_range_m: float = 60.0,
    merge_single_view: bool = True,
    bearing_sigma_deg: float = 1.0,
    ghost_conf: float = GHOST_CONF,
    max_rms_by_class: Mapping[str, float] | None = None,
    *,
    min_post_panos: int = 1,
    use_house_facade_edges: bool = False,
) -> list[Entity]:
    """Deduplicate observations into entities (see module docstring). ENU is relative to ref.

    `eps_by_class` overrides `CLUSTER_EPS` and is keyed by cluster key (POST_GROUP, GATE,
    HOUSE, BUILDING); any other key raises ValueError. A single-view detection with
    confidence below `ghost_conf` within eps of a triangulated entity of the same cluster
    key is dropped as a ghost. Single views without a usable ground contact (or, for houses
    and buildings, farther than `MAX_SINGLE_VIEW_RANGE_BY_CLASS`) are returned with method
    "unlocated" and NaN position (see `located_entities`). `max_rms_by_class` overrides
    `MAX_TRIANGULATION_RMS_M` (same keys as `eps_by_class`)."""
    _check_eps_keys(eps_by_class or {})
    _check_eps_keys(max_rms_by_class or {})
    eps_map = {**CLUSTER_EPS, **(eps_by_class or {})}
    rms_map = {**MAX_TRIANGULATION_RMS_M, **(max_rms_by_class or {})}
    # deterministic processing order regardless of input order
    obs_all = sorted(observations, key=lambda o: o.obs_id)
    out: list[Entity] = []
    by_cls: dict[str, list[Observation]] = defaultdict(list)
    for o in obs_all:
        by_cls[cluster_key(o.cls)].append(o)
    for cls in sorted(by_cls):
        obs = by_cls[cls]
        eps = eps_map.get(cls, DEFAULT_EPS)
        max_rms = rms_map.get(cls, eps)
        if use_house_facade_edges and cls == "HOUSE":
            max_rms = max(max_rms, 0.5 * SIZE_M.get("HOUSE", 10.0) + 2.0)
        accepted, leftovers = _cluster_class(
            obs, eps, cam_height_m, max_range_m, bearing_sigma_deg, max_rms=max_rms
        )
        groups = [(pt, list(idx), rms, "triangulated", math.nan) for pt, idx, rms in accepted]
        n_tri = len(groups)
        for i in leftovers:
            # a leftover ray that points at a triangulated entity (angular gate, and a pano
            # not yet in it) joins it; the single-view range is too fragile to decide this
            if merge_single_view and n_tri:
                costs = [
                    math.inf
                    if obs[i].pano_id in {obs[k].pano_id for k in groups[j][1]}
                    else ray_cost(
                        obs[i], groups[j][0], bearing_sigma_deg, max_range_m, cam_height_m
                    )
                    for j in range(n_tri)
                ]
                j = int(np.argmin(costs))
                if costs[j] <= LEFTOVER_GATE:
                    groups[j][1].append(i)
                    continue
            r = _single_view_range(obs[i], cam_height_m)
            if r is None:
                groups.append((np.full(3, np.nan), [i], math.nan, "unlocated", math.nan))
                continue
            p = tri.point_from_range(obs[i].ray, r)
            if merge_single_view and groups:
                d = [
                    np.linalg.norm(g[0][:2] - p[:2]) if g[3] != "unlocated" else math.inf
                    for g in groups
                ]
                j = int(np.argmin(d))
                pano_ids = {obs[k].pano_id for k in groups[j][1]}
                if d[j] <= eps and obs[i].pano_id not in pano_ids:
                    groups[j][1].append(i)
                    continue
            if cls in ("POST_GROUP", "STREET_TREE") and min_post_panos >= 2:
                groups.append((np.full(3, np.nan), [i], math.nan, "unlocated", r))
            else:
                groups.append((p, [i], math.nan, "single_view_ground_contact", r))
        tri_pts = [g[0] for g in groups if g[3] == "triangulated"]
        for pt, idx, rms, method, range_m in groups:
            members = [obs[i] for i in idx]
            if (
                cls in ("POST_GROUP", "STREET_TREE")
                and min_post_panos >= 2
                and len({m.pano_id for m in members}) < min_post_panos
            ):
                method = "unlocated"
                pt = np.full(3, np.nan)
                rms = math.nan
            elif use_house_facade_edges and cls == "HOUSE" and method == "triangulated":
                pt, rms = _refine_house_edges(members, pt, rms, max_range_m, max_rms)
            if method == "unlocated":
                lat = lng = math.nan
            else:
                lat, lng, _ = geo.enu_to_lla(pt[0], pt[1], pt[2], *ref_lla)

            # a weak single view within eps of a triangulated entity of the same cluster key
            # is a ghost of that entity (other keys are different objects and never compared)
            if (
                method == "single_view_ground_contact"
                and len(members) == 1
                and members[0].confidence < ghost_conf
            ):
                dist = min([float(np.linalg.norm(pt[:2] - t[:2])) for t in tri_pts] + [math.inf])
                if dist < eps:
                    continue

            # Class vote
            votes = defaultdict(float)
            for m in members:
                votes[m.cls] += m.confidence
            final_cls = max(votes, key=votes.get) if votes else cls

            attr_keys = sorted({k for m in members for k in m.attrs if m.cls == final_cls})
            attrs = {
                k: fuse_attribute(
                    (m.attrs.get(k), m.confidence)
                    for m in members
                    if m.cls == final_cls and m.attrs.get(k) is not None
                )
                for k in attr_keys
            }
            conf = float(
                1.0
                - np.prod([1.0 - min(0.999, m.confidence) for m in members if m.cls == final_cls])
            )
            eid = (
                _unlocated_id(final_cls, [m.obs_id for m in members])
                if method == "unlocated"
                else entity_id_for(final_cls, float(lat), float(lng))
            )
            out.append(
                Entity(
                    entity_id=eid,
                    cls=final_cls,
                    point_enu=np.asarray(pt, float),
                    lat=float(lat),
                    lng=float(lng),
                    obs_ids=[m.obs_id for m in members],
                    pano_ids=[m.pano_id for m in members],
                    method=method,
                    rms_m=float(rms),
                    confidence=conf,
                    attrs=attrs,
                    range_m=float(range_m),
                )
            )
    return _disambiguate_ids(out)


def _unlocated_id(cls: str, obs_ids: Sequence[str]) -> str:
    """Id of an entity without a position: derived from its observations, not a grid cell."""
    digest = hashlib.sha1("|".join(sorted(obs_ids)).encode()).hexdigest()[:10]
    return f"{cls.lower()}_unlocated_{digest}"


def _disambiguate_ids(entities: list[Entity]) -> list[Entity]:
    """Distinct objects closer than the id grid can hash to the same id; suffix repeats
    deterministically (_2, _3, ...) so ids stay unique and input-order independent."""
    entities.sort(
        key=lambda e: (
            e.entity_id,
            tuple(np.nan_to_num(np.round(e.point_enu, 2), nan=np.inf)),
            tuple(sorted(e.obs_ids)),
        )
    )
    seen: dict[str, int] = {}
    for e in entities:
        n = seen.get(e.entity_id, 0) + 1
        seen[e.entity_id] = n
        if n > 1:
            e.entity_id = f"{e.entity_id}_{n}"
    return entities


def labels_by_observation(entities: Iterable[Entity]) -> dict[str, str]:
    return {o: e.entity_id for e in entities for o in e.obs_ids}
