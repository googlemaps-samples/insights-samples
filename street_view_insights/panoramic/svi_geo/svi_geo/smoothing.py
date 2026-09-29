"""Temporal smoothing of per-pano labels and conversion to LINESTRING segments (pure code).

Continuous assets (road surface, sidewalk, fence, power line) are labelled per pano by Gemini
on code-rendered views; here the label sequence along a drive is denoised (majority filter or
an HMM/Viterbi pass with a stay probability) and turned into georeferenced segments, offset to
the side of the road in a local ENU frame.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Hashable, Sequence

import numpy as np
from shapely.geometry import LineString

from svi_geo import geo


def majority_filter(labels: Sequence[Hashable], window: int = 3) -> list[Hashable]:
    """Sliding-window majority; ties (or None majority) keep the original label."""
    n, h = len(labels), window // 2
    out = list(labels)
    for i in range(n):
        win = [x for x in labels[max(0, i - h) : i + h + 1] if x is not None]
        if not win:
            continue
        (top, c), *rest = Counter(win).most_common() or [(None, 0)]
        if rest and rest[0][1] == c:
            continue
        out[i] = top
    return out


def viterbi(
    labels: Sequence[Hashable | None],
    confidences: Sequence[float] | None = None,
    stay_prob: float = 0.9,
    states: Sequence[Hashable] | None = None,
) -> list[Hashable]:
    """Most likely label path given noisy per-pano labels.

    Emission: the observed label has probability = its confidence (default 0.8, floored just
    above 1/k), the remaining mass spread over the other states; `None` is uninformative.
    """
    states = (
        list(states)
        if states is not None
        else sorted({x for x in labels if x is not None}, key=str)
    )
    if not states:
        return list(labels)
    k, n = len(states), len(labels)
    conf = list(confidences) if confidences is not None else [0.8] * n
    idx = {s: i for i, s in enumerate(states)}
    log_t = np.full((k, k), math.log((1 - stay_prob) / max(1, k - 1)) if k > 1 else 0.0)
    np.fill_diagonal(log_t, math.log(stay_prob))
    em = np.zeros((n, k))
    for t, (lab, c) in enumerate(zip(labels, conf, strict=True)):
        if lab is None or lab not in idx:
            continue
        # an observation is never evidence against itself (QA S18): floor at just above 1/k
        c = min(max(float(c), 1.0 / k + 1e-6, 1e-3), 1 - 1e-3)
        em[t] = math.log((1 - c) / max(1, k - 1)) if k > 1 else 0.0
        em[t, idx[lab]] = math.log(c)
    score = em[0].copy()
    back = np.zeros((n, k), int)
    for t in range(1, n):
        cand = score[:, None] + log_t
        back[t] = cand.argmax(0)
        score = cand.max(0) + em[t]
    path = [int(score.argmax())]
    for t in range(n - 1, 0, -1):
        path.append(int(back[t, path[-1]]))
    return [states[i] for i in reversed(path)]


def _offset_enu(e: np.ndarray, n: np.ndarray, offset_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Shift a polyline sideways; positive = left of the direction of travel."""
    if len(e) < 2 or offset_m == 0:
        return e, n
    de, dn = np.gradient(e), np.gradient(n)
    norm = np.hypot(de, dn)
    norm[norm == 0] = 1.0
    # left normal of (de, dn) is (-dn, de)
    return e + offset_m * (-dn / norm), n + offset_m * (de / norm)


def segments_from_sequence(
    lat: Sequence[float],
    lng: Sequence[float],
    labels: Sequence[Hashable | None],
    offset_m: float = 0.0,
    breaks: Sequence[bool] | None = None,
    max_gap_m: float | None = None,
) -> list[dict]:
    """Runs of equal labels along an ordered drive -> segments with lat/lng LINESTRINGs.

    `breaks[i]` (or a jump > `max_gap_m` between pano i-1 and i) starts a new segment. Each
    run is extended half-way to its neighbours so consecutive segments meet.
    """
    lat = np.asarray(lat, float)
    lng = np.asarray(lng, float)
    n = len(lat)
    if n == 0:
        return []
    ref = (float(lat[0]), float(lng[0]), 0.0)
    e, nn, _ = geo.lla_to_enu(lat, lng, np.zeros(n), *ref)
    e, nn = np.atleast_1d(e).astype(float), np.atleast_1d(nn).astype(float)
    brk = np.zeros(n, bool) if breaks is None else np.asarray(breaks, bool).copy()
    if max_gap_m is not None and n > 1:
        brk[1:] |= np.hypot(np.diff(e), np.diff(nn)) > max_gap_m
    out: list[dict] = []
    start = 0
    for i in range(1, n + 1):
        if i == n or brk[i] or labels[i] != labels[start]:
            chunk_end = i  # exclusive
            # piece of the drive: [start, chunk_end) extended half-way to neighbours in-chunk
            lo = start
            hi = chunk_end - 1
            pe, pn = list(e[lo : hi + 1]), list(nn[lo : hi + 1])
            if lo > 0 and not brk[lo]:
                pe.insert(0, (e[lo - 1] + e[lo]) / 2)
                pn.insert(0, (nn[lo - 1] + nn[lo]) / 2)
            if hi < n - 1 and not brk[hi + 1]:
                pe.append((e[hi] + e[hi + 1]) / 2)
                pn.append((nn[hi] + nn[hi + 1]) / 2)
            if labels[start] is not None and len(pe) >= 2:
                oe, on = _offset_enu(np.array(pe), np.array(pn), offset_m)
                la, lo_, _ = geo.enu_to_lla(oe, on, np.zeros(len(oe)), *ref)
                line = LineString(list(zip(np.atleast_1d(lo_), np.atleast_1d(la), strict=True)))
                length = float(np.sum(np.hypot(np.diff(oe), np.diff(on))))
                out.append(
                    {
                        "label": labels[start],
                        "start_idx": start,
                        "end_idx": chunk_end - 1,
                        "n_panos": chunk_end - start,
                        "length_m": length,
                        "geometry": line,
                    }
                )
            start = i
    return out


def to_wkt_rows(segments: Sequence[dict], **extra) -> list[dict]:
    return [
        {**{k: v for k, v in s.items() if k != "geometry"}, "wkt": s["geometry"].wkt, **extra}
        for s in segments
    ]


def flicker_per_km(labels: Sequence[Hashable | None], length_m: float) -> float:
    """Label changes per km (ignoring None)."""
    seq = [x for x in labels if x is not None]
    changes = sum(1 for a, b in zip(seq, seq[1:], strict=False) if a != b)
    return changes / max(length_m / 1000.0, 1e-9)
