"""Label-free evaluation statistical core and reporting (pure code, no network I/O).

* `Measurement`: explicit ok/missing wrapper; a missing value is never replaced by 0 or NaN.
* `block_ratio_ci`: block bootstrap (`scipy.stats.bootstrap`, paired percentile, 2000 resamples)
  over spatial blocks of consecutive panos. Fewer than 5 clusters returns `missing`.
* `paired_diff_ci`: block bootstrap over per-cluster (after - before) differences.
* `kappa`: Cohen's kappa (`sklearn.metrics.cohen_kappa_score`), returning `missing` when both
  arms are constant.
* `mcnemar_exact`: two-sided exact binomial test (`scipy.stats.binomtest`) on discordant pairs.
* `decide_keep`: pre-registered keep rule with Holm-Bonferroni correction across at most 2
  primary metrics and non-inferiority guard checks.
* `METRIC_DOCS` and `render_summary`: mandatory "measures / does not measure" documentation,
  same-family teacher disclosure, manifest hashes, and spend accounting.
"""

from __future__ import annotations

import dataclasses
import inspect
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import cohen_kappa_score

from svi_geo import geo, sequence
from svi_geo import triangulate as tri

TEACHER_DISCLOSURE = (
    "agreement with Gemini 3.1 Pro Preview (same model family as student Gemini 3.5 Flash; "
    "not accuracy)"
)

_BOOTSTRAP_RNG_KEY = (
    "rng" if "rng" in inspect.signature(sp_stats.bootstrap).parameters else "random_state"
)


@dataclasses.dataclass(frozen=True)
class Measurement:
    """A measured statistic or an explicit missing-value record.

    Invariants enforced in `__post_init__`:
    * `status` is either `"ok"` or `"missing"`.
    * `value is None` if and only if `status == "missing"`.
    * When `status == "ok"`, `value` must be finite (never NaN or inf).
    * When `status == "missing"`, `reason` must be non-empty.
    """

    status: str
    value: float | None = None
    ci_lo: float | None = None
    ci_hi: float | None = None
    n_clusters: int = 0
    reason: str = ""
    placebo: float | None = None
    disclosure: str = ""

    def __post_init__(self) -> None:
        if self.status not in ("ok", "missing"):
            raise ValueError(f"status must be 'ok' or 'missing', got {self.status!r}")
        if self.status == "missing":
            if self.value is not None:
                raise ValueError("value must be None when status is 'missing'")
            if not str(self.reason).strip():
                raise ValueError("missing Measurement requires a non-empty reason")
        else:
            if self.value is None:
                raise ValueError("value cannot be None unless status is 'missing'")
            if not math.isfinite(float(self.value)):
                raise ValueError(f"ok Measurement value must be finite, got {self.value!r}")

    @classmethod
    def ok(
        cls,
        value: float,
        ci_lo: float | None = None,
        ci_hi: float | None = None,
        n_clusters: int = 0,
        placebo: float | None = None,
        disclosure: str = "",
    ) -> Measurement:
        return cls(
            status="ok",
            value=float(value),
            ci_lo=None if ci_lo is None else float(ci_lo),
            ci_hi=None if ci_hi is None else float(ci_hi),
            n_clusters=int(n_clusters),
            placebo=None if placebo is None else float(placebo),
            disclosure=disclosure,
        )

    @classmethod
    def missing(cls, reason: str, n_clusters: int = 0, disclosure: str = "") -> Measurement:
        return cls(
            status="missing",
            value=None,
            n_clusters=int(n_clusters),
            reason=str(reason).strip(),
            disclosure=disclosure,
        )

    def __str__(self) -> str:
        if self.status == "missing":
            return f"missing: {self.reason}"
        s = f"{self.value:.3f}"
        if self.ci_lo is not None and self.ci_hi is not None:
            s += f" [{self.ci_lo:.3f}, {self.ci_hi:.3f}]"
        if self.placebo is not None:
            s += f" (placebo {self.placebo:.3f})"
        return s

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def block_ratio_ci(
    per_cluster: Mapping[str, tuple[float, float]],
    n_boot: int = 2000,
    seed: int = 0,
    confidence_level: float = 0.95,
    min_clusters: int = 5,
    placebo: float | None = None,
    disclosure: str = "",
) -> Measurement:
    """Block-bootstrap percentile CI of `sum(num) / sum(den)` over clusters."""
    keys = [k for k in sorted(per_cluster) if float(per_cluster[k][1]) > 0]
    n_c = len(keys)
    if n_c < min_clusters:
        return Measurement.missing(
            f"fewer than {min_clusters} clusters with data (n={n_c})",
            n_clusters=n_c,
            disclosure=disclosure,
        )
    num = np.array([per_cluster[k][0] for k in keys], dtype=float)
    den = np.array([per_cluster[k][1] for k in keys], dtype=float)
    tot_den = float(den.sum())
    if tot_den <= 0:
        return Measurement.missing("zero denominator across clusters", n_clusters=n_c)
    point = float(num.sum() / tot_den)
    ratios = num / den
    if np.allclose(ratios, ratios[0]):
        return Measurement.ok(
            point, point, point, n_clusters=n_c, placebo=placebo, disclosure=disclosure
        )

    def _stat(n_arr: np.ndarray, d_arr: np.ndarray, axis: int = -1) -> np.ndarray:
        d_sum = np.sum(d_arr, axis=axis)
        return np.where(
            d_sum > 0, np.sum(n_arr, axis=axis) / np.where(d_sum > 0, d_sum, 1.0), np.nan
        )

    rng = np.random.default_rng(seed)
    res = sp_stats.bootstrap(
        (num, den),
        _stat,
        n_resamples=int(n_boot),
        paired=True,
        vectorized=True,
        confidence_level=float(confidence_level),
        method="percentile",
        **{_BOOTSTRAP_RNG_KEY: rng},
    )
    lo = float(res.confidence_interval.low)
    hi = float(res.confidence_interval.high)
    if not (math.isfinite(lo) and math.isfinite(hi)):
        lo, hi = point, point
    return Measurement.ok(
        point,
        min(lo, point),
        max(hi, point),
        n_clusters=n_c,
        placebo=placebo,
        disclosure=disclosure,
    )


def paired_diff_ci(
    before: Mapping[str, float],
    after: Mapping[str, float],
    n_boot: int = 2000,
    seed: int = 0,
    confidence_level: float = 0.95,
    min_clusters: int = 5,
) -> Measurement:
    """Block-bootstrap percentile CI of the per-cluster difference `after[k] - before[k]`."""
    if set(before.keys()) != set(after.keys()):
        raise ValueError("mismatched cluster keys between before and after")
    keys = sorted(before.keys())
    n_c = len(keys)
    if n_c < min_clusters:
        return Measurement.missing(f"fewer than {min_clusters} clusters (n={n_c})", n_clusters=n_c)
    diffs = np.array([float(after[k]) - float(before[k]) for k in keys], dtype=float)
    if not np.all(np.isfinite(diffs)):
        return Measurement.missing("non-finite cluster differences", n_clusters=n_c)
    point = float(np.mean(diffs))
    if np.allclose(diffs, diffs[0]):
        return Measurement.ok(point, point, point, n_clusters=n_c)
    rng = np.random.default_rng(seed)
    res = sp_stats.bootstrap(
        (diffs,),
        np.mean,
        n_resamples=int(n_boot),
        vectorized=True,
        confidence_level=float(confidence_level),
        method="percentile",
        **{_BOOTSTRAP_RNG_KEY: rng},
    )
    lo = float(res.confidence_interval.low)
    hi = float(res.confidence_interval.high)
    return Measurement.ok(point, min(lo, point), max(hi, point), n_clusters=n_c)


def kappa(y1: Sequence[Any], y2: Sequence[Any], disclosure: str = "") -> Measurement:
    """Cohen's kappa on paired non-None labels; returns `missing` when labels are constant."""
    if len(y1) != len(y2):
        raise ValueError(f"y1 and y2 must have equal length ({len(y1)} != {len(y2)})")
    pairs = [
        (str(a), str(b)) for a, b in zip(y1, y2, strict=True) if a is not None and b is not None
    ]
    n = len(pairs)
    if n < 2:
        return Measurement.missing(f"fewer than 2 paired labels (n={n})", n_clusters=n)
    a_vals = [p[0] for p in pairs]
    b_vals = [p[1] for p in pairs]
    if len(set(a_vals) | set(b_vals)) < 2:
        return Measurement.missing(
            "constant labels on both sides; Cohen kappa is undefined",
            n_clusters=n,
            disclosure=disclosure,
        )
    val = float(cohen_kappa_score(a_vals, b_vals))
    if not math.isfinite(val):
        return Measurement.missing("degenerate label distribution for kappa", n_clusters=n)
    return Measurement.ok(val, n_clusters=n, disclosure=disclosure)


def mcnemar_exact(b: int, c: int) -> Measurement:
    """Two-sided exact McNemar p-value via `scipy.stats.binomtest` on discordant counts (b, c)."""
    if b < 0 or c < 0:
        raise ValueError("discordant counts b and c must be non-negative")
    n = int(b) + int(c)
    if n == 0:
        return Measurement.missing("no discordant pairs (b + c = 0)", n_clusters=0)
    pval = float(
        sp_stats.binomtest(min(int(b), int(c)), n=n, p=0.5, alternative="two-sided").pvalue
    )
    return Measurement.ok(pval, n_clusters=n)


def adjacent_agreement(labels: Sequence[Any]) -> float | None:
    """Raw agreement between consecutive non-None elements in a sequence."""
    seq = [x for x in labels if x is not None]
    if len(seq) < 2:
        return None
    return float(sum(a == b for a, b in zip(seq[:-1], seq[1:], strict=True)) / (len(seq) - 1))


def shuffle_baseline(labels: Sequence[Any], n_shuffles: int = 500, seed: int = 0) -> float | None:
    """Expected adjacent agreement when the non-None labels of `labels` are shuffled."""
    seq = [x for x in labels if x is not None]
    if len(seq) < 2:
        return None
    rng = np.random.default_rng(seed)
    arr = np.asarray(seq, dtype=object)
    scores = []
    for _ in range(int(n_shuffles)):
        perm = rng.permutation(arr)
        scores.append(float(np.mean(perm[:-1] == perm[1:])))
    return float(np.mean(scores))


def _one_sided_good(meas: Measurement, direction: str) -> bool:
    if meas.status != "ok" or meas.value is None or meas.ci_lo is None or meas.ci_hi is None:
        return False
    if direction == "higher":
        return meas.ci_lo > 0.0 and meas.value > 0.0
    if direction == "lower":
        return meas.ci_hi < 0.0 and meas.value < 0.0
    raise ValueError(f"direction must be 'higher' or 'lower', got {direction!r}")


def _approx_pvalue_from_ci(meas: Measurement, direction: str) -> float:
    """Two-sided p-value approximated from the 95% CI width, or 1.0 if in the wrong direction."""
    if not _one_sided_good(meas, direction):
        return 1.0
    assert meas.value is not None and meas.ci_lo is not None and meas.ci_hi is not None
    se = (meas.ci_hi - meas.ci_lo) / (2.0 * 1.959963984540054)
    if se <= 1e-12:
        return 0.0
    z = abs(meas.value) / se
    return float(2.0 * sp_stats.norm.sf(z))


def repeat_pass_agreement_vs_placebo(
    pairs_a: Sequence[Any],
    pairs_b: Sequence[Any],
    block_ids: Sequence[str] | None = None,
    *,
    n_shuffles: int = 500,
    seed: int = 0,
    min_clusters: int = 2,
) -> Measurement:
    """Compute cross-day repeat-pass agreement on paired observations vs a shuffled-pair placebo.

    Disclosed as 'consistency across capture days != ground-truth accuracy'.
    """
    if len(pairs_a) != len(pairs_b):
        raise ValueError(
            f"pairs_a and pairs_b must have equal length ({len(pairs_a)} != {len(pairs_b)})"
        )
    if block_ids is not None and len(block_ids) != len(pairs_a):
        raise ValueError("block_ids must have the same length as pairs_a")
    valid_idx = [
        i
        for i, (a, b) in enumerate(zip(pairs_a, pairs_b, strict=True))
        if a is not None and b is not None
    ]
    if len(valid_idx) < 2:
        return Measurement.missing(
            f"fewer than 2 valid repeat-pass pairs (n={len(valid_idx)})",
            n_clusters=len(valid_idx),
            disclosure="cross-day repeat-pass consistency != accuracy",
        )
    a_arr = np.asarray([str(pairs_a[i]) for i in valid_idx], dtype=object)
    b_arr = np.asarray([str(pairs_b[i]) for i in valid_idx], dtype=object)
    blks = (
        [str(block_ids[i]) for i in valid_idx]
        if block_ids is not None
        else [f"p{i:03d}" for i in range(len(valid_idx))]
    )
    rng = np.random.default_rng(seed)
    shuf_scores = []
    for _ in range(int(n_shuffles)):
        perm_b = rng.permutation(b_arr)
        shuf_scores.append(float(np.mean(a_arr == perm_b)))
    placebo_val = float(np.mean(shuf_scores))

    per_cluster: dict[str, tuple[float, float]] = {}
    for blk, a_val, b_val in zip(blks, a_arr, b_arr, strict=True):
        prev_n, prev_d = per_cluster.get(blk, (0.0, 0.0))
        per_cluster[blk] = (prev_n + (1.0 if a_val == b_val else 0.0), prev_d + 1.0)

    eff_min = min(min_clusters, len(per_cluster)) if len(per_cluster) >= 2 else 2
    return block_ratio_ci(
        per_cluster,
        seed=seed,
        min_clusters=eff_min,
        placebo=placebo_val,
        disclosure="cross-day repeat-pass consistency != accuracy",
    )


def decide_keep(
    primaries: Sequence[tuple[str, Measurement, str]],
    guards: Sequence[tuple[str, Measurement, float, str]] = (),
    alpha: float = 0.05,
    cost_diff_usd: Measurement | float | None = None,
    max_cost_delta_usd: float = 0.0,
) -> dict[str, Any]:
    """Pre-registered keep decision (§3 / §4.6):
    * At most 2 primary metrics `(metric_id, paired_diff_measurement, direction)`.
    * Primary paired-difference 95% CI must exclude 0 in the good direction and pass
      Holm-Bonferroni step-down correction at level `alpha` across `m = len(primaries)` primaries.
    * No guard metric `(metric_id, paired_diff_measurement, delta, direction)` has its CI lying
      entirely beyond `delta` in the bad direction.
    * Optional cost guard: if `cost_diff_usd` is provided, paired cost difference must not
      exceed `max_cost_delta_usd` (for a `Measurement`, `ci_lo > max_cost_delta_usd` or
      `value > max_cost_delta_usd` when `ci_lo` is None; for a scalar float, `cost_diff_usd > max_cost_delta_usd`).
    """
    if not primaries or len(primaries) > 2:
        raise ValueError("decide_keep requires 1 or 2 primary metrics")

    if cost_diff_usd is not None:
        if isinstance(cost_diff_usd, Measurement):
            if cost_diff_usd.status != "ok" or cost_diff_usd.value is None:
                return {"keep": False, "reason": f"cost guard is missing ({cost_diff_usd})"}
            c_lo = cost_diff_usd.ci_lo if cost_diff_usd.ci_lo is not None else cost_diff_usd.value
            if c_lo > float(max_cost_delta_usd):
                return {
                    "keep": False,
                    "reason": (
                        f"cost guard breach: cost_diff_usd={cost_diff_usd} "
                        f"exceeds +{float(max_cost_delta_usd):.4f}"
                    ),
                }
        else:
            c_val = float(cost_diff_usd)
            if c_val > float(max_cost_delta_usd):
                return {
                    "keep": False,
                    "reason": (
                        f"cost guard breach: cost_diff_usd={c_val:+.4f} "
                        f"exceeds +{float(max_cost_delta_usd):.4f}"
                    ),
                }

    for gid, gmeas, delta, gdir in guards:
        if gmeas.status != "ok" or gmeas.ci_lo is None or gmeas.ci_hi is None:
            return {"keep": False, "reason": f"guard {gid} is missing ({gmeas})"}
        d = abs(float(delta))
        if gdir == "higher" and gmeas.ci_hi < -d:
            return {
                "keep": False,
                "reason": f"guard breach on {gid}: CI [{gmeas.ci_lo:.3f}, {gmeas.ci_hi:.3f}] lies entirely below -{d:.3f}",
            }
        if gdir == "lower" and gmeas.ci_lo > d:
            return {
                "keep": False,
                "reason": f"guard breach on {gid}: CI [{gmeas.ci_lo:.3f}, {gmeas.ci_hi:.3f}] lies entirely above +{d:.3f}",
            }

    m = len(primaries)
    scored = []
    for pid, pmeas, pdir in primaries:
        if pmeas.status != "ok":
            return {"keep": False, "reason": f"primary {pid} is missing ({pmeas})"}
        good = _one_sided_good(pmeas, pdir)
        p_val = _approx_pvalue_from_ci(pmeas, pdir)
        scored.append((p_val, pid, pmeas, pdir, good))

    scored.sort(key=lambda x: x[0])
    for rank, (p_val, pid, pmeas, _pdir, good) in enumerate(scored):
        holm_alpha = alpha / (m - rank)
        if not good or p_val > holm_alpha:
            return {
                "keep": False,
                "reason": (
                    f"Holm-corrected primary check failed on {pid}: "
                    f"diff={pmeas}, p={p_val:.4f} > {holm_alpha:.4f}"
                ),
            }

    return {
        "keep": True,
        "reason": "all primary metrics passed Holm-corrected 95% CI check and all guards held",
    }


METRIC_DOCS: dict[str, dict[str, str]] = {
    "M1.1": {
        "uc": "UC1",
        "name": "Fused attribute test-retest agreement (raw and Cohen kappa)",
        "signal": "e",
        "role": "primary",
        "measures": "Stability of fused house attributes (stories, exterior_material, roof_type) across 3 perturbed reruns (yaw +-3 deg, hfov +-10%, paraphrase, seed).",
        "does_not_measure": "True architectural ground truth; systematic bias shared across perturbations.",
    },
    "M1.2": {
        "uc": "UC1",
        "name": "Location repeatability (p50/p90 rerun distance and split-half distance)",
        "signal": "a, e",
        "role": "primary",
        "measures": "Geometric consistency of triangulated house positions across disjoint pano halves and perturbed reruns.",
        "does_not_measure": "Absolute parcel centroid offset when all views see the front facade rather than the roof centre.",
    },
    "M1.3": {
        "uc": "UC1",
        "name": "Held-out reprojection hit rate and angular error",
        "signal": "a",
        "role": "guard",
        "measures": "Whether the house point triangulated from k-1 views projects inside the detected house box in the k-th held-out view.",
        "does_not_measure": "Errors on houses seen from fewer than 3 views.",
    },
    "M1.4": {
        "uc": "UC1",
        "name": "Framing quality (border-truncation rate, OpenCV sky contact, teacher framing)",
        "signal": "d, c",
        "role": "secondary",
        "measures": "Whether selected house views contain the full facade without border truncation and have sky above the roof.",
        "does_not_measure": "Attribute classification correctness once the house is framed.",
    },
    "M1.5": {
        "uc": "UC1",
        "name": "Entity ID carry-over rate within 3 m across reruns and repeat passes",
        "signal": "e, b",
        "role": "secondary",
        "measures": "Stability of matched house identities across reruns and independent capture days.",
        "does_not_measure": "Correctness of the underlying house attributes.",
    },
    "M1.6": {
        "uc": "UC1",
        "name": "Repeat-pass attribute agreement across capture days",
        "signal": "b",
        "role": "secondary",
        "measures": "Cross-day reproducibility of fused house attributes under real lighting, season, and camera-pose changes.",
        "does_not_measure": "Legitimate physical renovations between capture dates or shared model bias.",
    },
    "M1.7": {
        "uc": "UC1",
        "name": "Cross-day repeat-pass house attribute agreement vs shuffled-pair placebo",
        "signal": "b",
        "role": "secondary",
        "measures": "Agreement of fused house attributes on matched cross-day capture pairs above a shuffled-pair placebo baseline (consistency != accuracy).",
        "does_not_measure": "Ground-truth architectural accuracy or physical renovations between capture dates.",
    },
    "M2.1": {
        "uc": "UC2",
        "name": "Held-out-view reprojection support per located entity",
        "signal": "a",
        "role": "primary",
        "measures": "Share of predicted-visible held-out panos that contain a same-class detection box covering the reprojected 3D bearing.",
        "does_not_measure": "Objects consistently missed in all views or systematic hallucinations that happen to triangulate.",
    },
    "M2.2": {
        "uc": "UC2",
        "name": "Test-retest entity recall in both directions under perturbation",
        "signal": "e",
        "role": "guard",
        "measures": "Spatial recall of deduplicated entities across perturbed reruns via Hungarian matching.",
        "does_not_measure": "False positives that repeat identically across perturbations.",
    },
    "M2.3": {
        "uc": "UC2",
        "name": "Repeat-pass entity recall (multi-view entities only)",
        "signal": "b",
        "role": "secondary",
        "measures": "Cross-day spatial recall of triangulated street assets across independent drives on different dates.",
        "does_not_measure": "Temporary or newly installed street furniture between capture dates.",
    },
    "M2.4": {
        "uc": "UC2",
        "name": "OpenCV vertical-structure support for pole and sign boxes vs placebo",
        "signal": "d",
        "role": "secondary",
        "measures": "Gemini-independent LSD vertical post/edge support inside detected pole boxes and below sign plates compared with random boxes.",
        "does_not_measure": "Signs mounted flush on walls or overhead gantries without a vertical post.",
    },
    "M2.5": {
        "uc": "UC2",
        "name": "Located share per class, HOUSE unlocated share, and >=2-pano share",
        "signal": "a",
        "role": "guard",
        "measures": "Fraction of entities with a valid 3D position and multi-view support (density is reported only, never a target).",
        "does_not_measure": "True object precision or recall against a ground-truth map.",
    },
    "M2.6": {
        "uc": "UC2",
        "name": "Silver-teacher confirmation on high-res zoom tiles vs placebo",
        "signal": "c",
        "role": "secondary",
        "measures": "Agreement with Gemini 3.1 Pro Preview on 2x2 zoom tiles at the projected bearing (same model family; not accuracy).",
        "does_not_measure": "Errors shared across the Gemini model family.",
    },
    "M3.1": {
        "uc": "UC3",
        "name": "Perturbation Cohen kappa per surface slot (CENTER, LEFT, RIGHT)",
        "signal": "e",
        "role": "primary",
        "measures": "Consistency of road and sidewalk material/presence labels across crop, pitch, yaw, prompt paraphrase, and window perturbations.",
        "does_not_measure": "Ground-truth pavement material accuracy when the model is consistently biased.",
    },
    "M3.2": {
        "uc": "UC3",
        "name": "Adjacent-pano raw agreement vs within-sequence shuffle baseline",
        "signal": "a, e",
        "role": "secondary",
        "measures": "Along-drive spatial continuity of surface material labels above the marginal label-frequency baseline.",
        "does_not_measure": "Whether transitions occur at the exact metre of a real pavement change.",
    },
    "M3.3": {
        "uc": "UC3",
        "name": "Repeat-pass agreement per 20 m bin across capture days",
        "signal": "b",
        "role": "secondary",
        "measures": "Cross-day reproducibility of road and sidewalk labels on the same 20 m road segment.",
        "does_not_measure": "Repaving between capture dates or shared family bias.",
    },
    "M3.4": {
        "uc": "UC3",
        "name": "OpenCV road texture/colour descriptor consistency (within vs between segments)",
        "signal": "d",
        "role": "secondary",
        "measures": "Gemini-independent Lab + LBP texture separation between predicted material segments vs within segments.",
        "does_not_measure": "Semantic material names when shadows or wet pavement alter appearance.",
    },
    "M3.5": {
        "uc": "UC3",
        "name": "Cohen kappa between sidewalk presence and OpenCV IPM kerb-line evidence",
        "signal": "d",
        "role": "secondary",
        "measures": "Agreement between Gemini sidewalk ABSENT/present calls and geometric kerb/walkway lines in the ground-plane inverse perspective map.",
        "does_not_measure": "Sidewalks hidden behind parked cars or flush kerbless walkways.",
    },
    "M3.6": {
        "uc": "UC3",
        "name": "Silver-teacher agreement per surface slot vs shuffle placebo",
        "signal": "c",
        "role": "guard",
        "measures": "Agreement with Gemini 3.1 Pro Preview on zoom tiles per slot (same model family; not accuracy).",
        "does_not_measure": "Errors shared across the Gemini model family.",
    },
    "M3.7": {
        "uc": "UC3",
        "name": "Cross-day repeat-pass surface agreement vs shuffled-pair placebo",
        "signal": "b",
        "role": "secondary",
        "measures": "Cross-day surface slot agreement across matched 20 m bins compared against a shuffled-pair placebo baseline (consistency != accuracy).",
        "does_not_measure": "Ground-truth pavement accuracy or repaving between capture dates.",
    },
    "M4.1": {
        "uc": "UC4",
        "name": "Occlusion screen skip precision and pass precision vs silver teacher",
        "signal": "c",
        "role": "primary",
        "measures": "How accurately the code occlusion screen skips views where the roof is occluded and passes views with >=50% roof visibility according to the teacher.",
        "does_not_measure": "Geometric accuracy of the traced roof polylines.",
    },
    "M4.2": {
        "uc": "UC4",
        "name": "OpenCV wall-decoy acceptance rate vs roof-band random baseline",
        "signal": "d",
        "role": "primary",
        "measures": "Share of non-roof straight edges (LSD lines in wall_box, horizon, wall base, siding) erroneously accepted by the roof validator.",
        "does_not_measure": "Recall of faint or low-contrast true roof ridges.",
    },
    "M4.3": {
        "uc": "UC4",
        "name": "Validator retention (share of Gemini edges accepted and views with >=1 edge)",
        "signal": "d",
        "role": "guard",
        "measures": "Ensure tightening the roof validator does not reject all proposed roof edges.",
        "does_not_measure": "Whether retained edges are true roof boundaries on its own (must be paired with M4.2).",
    },
    "M4.4": {
        "uc": "UC4",
        "name": "Test-retest polyline agreement within 5 px by edge type",
        "signal": "e",
        "role": "secondary",
        "measures": "Repeatability of accepted roof polylines across perturbed views.",
        "does_not_measure": "Systematic snapping to a salient non-roof edge.",
    },
    "M4.5": {
        "uc": "UC4",
        "name": "Silver-teacher roof trace F1 within 5 px",
        "signal": "c",
        "role": "secondary",
        "measures": "Polyline F1 within 5 px against Gemini 3.1 Pro Preview traces on zoom tiles (same model family; not accuracy).",
        "does_not_measure": "Sub-pixel photogrammetric accuracy against LiDAR.",
    },
    "M4.6": {
        "uc": "UC4",
        "name": "3-view eave triangulation and held-out reprojection residual",
        "signal": "a",
        "role": "secondary",
        "measures": "3D geometric consistency of an eave line triangulated from 2 views and reprojected into a 3rd view.",
        "does_not_measure": "Views where fewer than 3 cameras see the same eave.",
    },
}


def render_summary(results: Mapping[str, Any]) -> str:
    """Render a complete Markdown report with disclosures, manifest hashes, spend, and metric docs."""
    date = results.get("date", "unknown")
    commit = results.get("commit", "unknown")
    manifests = results.get("manifests") or {}
    spend = results.get("spend") or {}
    metrics: Mapping[str, Measurement | Mapping[str, Any]] = results.get("metrics") or {}

    lines = [
        "# Label-Free Evaluation Summary",
        "",
        "> **Disclosure:** Label-free evaluation. No human labels, no external map data. "
        "All numbers measure multi-view geometric consistency, cross-day repeat-pass stability, "
        "OpenCV image-evidence support, or "
        f"{TEACHER_DISCLOSURE}.",
        "",
        f"- **Date:** `{date}`",
        f"- **Commit:** `{commit}`",
    ]
    if manifests:
        m_str = ", ".join(f"{k}=`{v}`" for k, v in sorted(manifests.items()))
        lines.append(f"- **Manifests:** {m_str}")
    if spend:
        usd = float(spend.get("usd", 0.0))
        calls = int(spend.get("calls", 0))
        inp = int(spend.get("input_tokens", 0))
        out = int(spend.get("output_tokens", 0))
        lines.append(
            f"- **Spend:** `${usd:.2f}` ({calls} calls, {inp:,} input tokens, {out:,} output tokens)"
        )
    lines.extend(
        [
            "",
            "| Metric | UC | Role | Signal | Value (95% CI) | Measures | Does Not Measure |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for mid in sorted(METRIC_DOCS.keys()):
        doc = METRIC_DOCS[mid]
        m = metrics.get(mid)
        if isinstance(m, Measurement):
            val_str = str(m)
        elif isinstance(m, Mapping):
            m_obj = Measurement(**m)
            val_str = str(m_obj)
        else:
            val_str = "missing: not run"
        lines.append(
            f"| `{mid}` ({doc['name']}) | {doc['uc']} | {doc['role']} | {doc['signal']} | "
            f"{val_str} | {doc['measures']} | {doc['does_not_measure']} |"
        )
    return "\n".join(lines) + "\n"


def _extract_ray(item: Any) -> tri.Ray:
    """Extract a `tri.Ray` from either a `tri.Ray` or an `ent.Observation`-like object."""
    return item.ray if hasattr(item, "ray") else item


def heldout_reprojection(
    by_obj: Mapping[str, Sequence[Any]],
    tol_deg: float = 2.0,
    test_bias_deg: float = 0.0,
    bias_fraction: float = 0.0,
    max_range_m: float = 60.0,
    max_rms_m: float = 6.0,
) -> dict[str, Any]:
    """Leave-one-out bearing reprojection across multi-view object observations.

    For each object with `>= 3` observations, holds out the `k`-th ray, triangulates the
    3D/2D position from the remaining `m - 1` rays via `tri.intersect_rays`, and measures
    the angular residual (degrees) between the reprojected azimuth from the held-out camera
    origin to the triangulated point and the held-out ray's observed azimuth.

    If `test_bias_deg != 0.0` and `bias_fraction > 0.0`, deterministic synthetic bias is
    injected into a fraction `bias_fraction` of held-out evaluations (for unit testing
    sensitivity).
    """
    errors: list[float] = []
    hits: list[int] = []
    eval_idx = 0
    for obj_id in sorted(by_obj.keys()):
        obs_list = list(by_obj[obj_id])
        if len(obs_list) < 3:
            continue
        rays = [_extract_ray(o) for o in obs_list]
        for k in range(len(rays)):
            train_rays = rays[:k] + rays[k + 1 :]
            res = tri.intersect_rays(train_rays, max_range_m=max_range_m, max_rms_m=max_rms_m)
            if not res.ok or res.point is None:
                continue
            target_ray = rays[k]
            vec = res.point[:2] - target_ray.origin[:2]
            if float(np.linalg.norm(vec)) < 1e-3:
                continue
            pred_az = float(geo.enu_bearing_deg(float(vec[0]), float(vec[1])))
            obs_az = float(target_ray.az_deg)
            if test_bias_deg != 0.0 and bias_fraction > 0.0:
                # Deterministic staggered selection achieving exact fraction on even counts
                stride = max(1, round(1.0 / bias_fraction))
                if (eval_idx % stride) == 0:
                    obs_az = (obs_az + test_bias_deg) % 360.0
            eval_idx += 1
            err = abs(float(geo.angdiff(pred_az, obs_az)))
            errors.append(err)
            hits.append(1 if err <= tol_deg else 0)
    if not errors:
        return {
            "n_evals": 0,
            "hit_rate": float("nan"),
            "median_error_deg": float("nan"),
            "p90_error_deg": float("nan"),
            "errors_deg": [],
        }
    arr = np.asarray(errors, dtype=float)
    return {
        "n_evals": len(errors),
        "hit_rate": float(np.mean(hits)),
        "median_error_deg": float(np.median(arr)),
        "p90_error_deg": float(np.percentile(arr, 90)),
        "errors_deg": errors,
    }


def split_half_location(
    objects_rays: Sequence[Sequence[Any]],
    max_range_m: float = 60.0,
    max_rms_m: float = 8.0,
) -> dict[str, Any]:
    """Split each object's `>= 4` rays into even (`0::2`) and odd (`1::2`) subsets, triangulate
    both independently, and compute the horizontal distance (metres) between the two estimates."""
    dists: list[float] = []
    for item_seq in objects_rays:
        rays = [_extract_ray(r) for r in item_seq]
        if len(rays) < 4:
            continue
        even = rays[0::2]
        odd = rays[1::2]
        res_e = tri.intersect_rays(even, max_range_m=max_range_m, max_rms_m=max_rms_m)
        res_o = tri.intersect_rays(odd, max_range_m=max_range_m, max_rms_m=max_rms_m)
        if not (res_e.ok and res_o.ok and res_e.point is not None and res_o.point is not None):
            continue
        d = float(np.linalg.norm(res_e.point[:2] - res_o.point[:2]))
        dists.append(d)
    if not dists:
        return {
            "n_valid": 0,
            "p50_m": float("nan"),
            "p90_m": float("nan"),
            "distances_m": [],
        }
    arr = np.asarray(dists, dtype=float)
    return {
        "n_valid": len(dists),
        "p50_m": float(np.median(arr)),
        "p90_m": float(np.percentile(arr, 90)),
        "distances_m": dists,
    }


def repeat_pairs(
    seqs: pd.DataFrame,
    max_sep_m: float = 15.0,
    min_overlap_m: float = 80.0,
    min_matched_panos: int = 3,
) -> list[dict[str, Any]]:
    """Delegate to `sequence.repeat_pairs` for cross-day overlapping drive sequences."""
    return sequence.repeat_pairs(
        seqs,
        max_sep_m=max_sep_m,
        min_overlap_m=min_overlap_m,
        min_matched_panos=min_matched_panos,
    )


def blocks(seqs: pd.DataFrame, block_size: int = 5) -> dict[str, str]:
    """Delegate to `sequence.blocks` for spatial block assignment."""
    return sequence.blocks(seqs, block_size=block_size)


def perturbations(seed: int = 0, n: int = 3) -> list[dict[str, Any]]:
    """Deterministic view/prompt perturbation specs for test-retest repeatability (signal e)."""
    rng = np.random.default_rng(seed)
    out: list[dict[str, Any]] = []
    for i in range(n):
        out.append(
            {
                "idx": i,
                "yaw_delta_deg": float(rng.uniform(-3.0, 3.0)),
                "hfov_scale": float(rng.uniform(0.90, 1.10)),
                "gemini_seed": int(rng.integers(1, 2**31 - 1)),
            }
        )
    return out
