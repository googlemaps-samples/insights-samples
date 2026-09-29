#!/usr/bin/env python3
"""T3c overlap feasibility probe: do adjacent rosette cameras (k, k+1 mod 6) overlap?

For each adjacent pair: SIFT + Lowe ratio 0.75 + RANSAC fundamental matrix on pixels.
Gate: >= 30 inliers on >= 4 of 6 pairs per pano. Also reports where inliers sit
(normalised x in each frame; expected near the facing edges).
"""

from __future__ import annotations

import argparse
import json

import cv2
import numpy as np
import pandas as pd
from google.cloud import storage

from svi_geo import auth, data, images, rosette


def load_gray(fetcher, uri: str) -> np.ndarray:
    return images.decode(fetcher.fetch(uri), scale=0.5, gray=True)


def feature_mask(gray: np.ndarray) -> np.ndarray:
    m = rosette.privacy_blob_mask(gray) & rosette.textured_mask(gray)
    h = gray.shape[0]
    m[int(0.80 * h) :, :] = False  # vehicle hood region (coarse, deterministic)
    return m.astype(np.uint8) * 255


def match_pair(sift, g1, g2, m1, m2, ratio=0.75):
    k1, d1 = sift.detectAndCompute(g1, m1)
    k2, d2 = sift.detectAndCompute(g2, m2)
    if d1 is None or d2 is None or len(k1) < 8 or len(k2) < 8:
        return np.zeros((0, 2)), np.zeros((0, 2))
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    good = []
    for pair in matcher.knnMatch(d1, d2, k=2):
        if len(pair) == 2 and pair[0].distance < ratio * pair[1].distance:
            good.append(pair[0])
    p1 = np.float64([k1[m.queryIdx].pt for m in good])
    p2 = np.float64([k2[m.trainIdx].pt for m in good])
    return p1, p2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panos", default="data/calib_panos.parquet")
    ap.add_argument("--n-panos", type=int, default=3)
    ap.add_argument("--out", default="data/probe_overlap.json")
    args = ap.parse_args()
    calib = pd.read_parquet(args.panos)
    train = calib[calib["split"] == "train"]
    pano_ids = list(dict.fromkeys(train.groupby("aoi")["pano_id"].first()))[: args.n_panos]
    fetcher = images.GcsImageFetcher(
        storage.Client(project=data.PROJECT, credentials=auth.get_credentials())
    )
    sift = cv2.SIFT_create(nfeatures=8000)
    report = []
    for pid in pano_ids:
        fr = calib[calib["pano_id"] == pid].set_index("cam_k")
        grays = {k: load_gray(fetcher, fr.loc[k, "gcs_uri"]) for k in range(6) if k in fr.index}
        masks = {k: feature_mask(g) for k, g in grays.items()}
        pairs_ok = 0
        for k in range(6):
            k2 = (k + 1) % 6
            if k not in grays or k2 not in grays:
                continue
            p1, p2 = match_pair(sift, grays[k], grays[k2], masks[k], masks[k2])
            n_inl, x1, x2 = 0, float("nan"), float("nan")
            if len(p1) >= 8:
                F, inl = cv2.findFundamentalMat(p1, p2, cv2.FM_RANSAC, 3.0, 0.999)
                if inl is not None:
                    inl = inl.ravel().astype(bool)
                    n_inl = int(inl.sum())
                    w = grays[k].shape[1]
                    if n_inl:
                        x1 = float(np.median(p1[inl, 0]) / w)
                        x2 = float(np.median(p2[inl, 0]) / w)
            pairs_ok += n_inl >= 30
            h1 = fr.loc[k, "camera_pose"]["heading"]
            h2 = fr.loc[k2, "camera_pose"]["heading"]
            row = {
                "pano_id": pid,
                "pair": [k, k2],
                "heading_gap_deg": float(np.mod(h2 - h1, 360)),
                "ratio_matches": int(len(p1)),
                "inliers": n_inl,
                "median_x_frac_cam_k": x1,
                "median_x_frac_cam_k1": x2,
            }
            report.append(row)
            print(json.dumps(row))
        print(
            f"pano {pid}: {pairs_ok}/6 pairs with >= 30 inliers -> {'PASS' if pairs_ok >= 4 else 'FAIL'}"
        )
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
