#!/usr/bin/env python3
"""Render a hand-label kit from real imagery (no labels are generated here).

    ../../../.venv/bin/python scripts/make_label_kit.py \
        --aoi 40.0150,-105.2705 --aoi 39.7392,-104.9903 \
        --houses houses.csv --out ~/svi_label_kit/2026-01-01

For each AOI it takes `--n-panos` consecutive panos of the longest drive sequence and renders,
with the same field-of-view rules as the notebooks:

- UC2: the 6 level ground views of every pano (`pipeline.views_for_pano`);
- UC3: front/left/right road views centred on the travel direction (`sequence.road_view`);
- UC1 (with `--houses`): every candidate view of each target house (`views.house_view_candidates`);
- UC4 (with `--houses`): the roof views of each target house (`views.rank_roof_views`).

It writes JPGs, one HTML page per use case and a pre-filled `labels.csv` (header in
`labelkit.HEADER`), plus `second_labeller_panos.txt`. A human fills the CSV; see EVALUATION.md.
Images are rendered from frames downloaded with your credentials and stay local: do not commit
or redistribute the kit. BigQuery: pano tables only, dry run first, 2 GB cap, no gcs_uri column.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

import pandas as pd

from svi_geo import auth, config, data, images, labelkit, pipeline, roof, rosette, sequence, views

ROAD_VIEW_PITCH = -22.0  # as in the UC3 notebook
HOUSE_VIEW = (1024, 768)  # as in the UC1 notebook
ROOF_VIEW = (1200, 900)  # as in the UC4 notebook
MAX_BLACK = 0.01


def parse_latlng(s: str) -> tuple[float, float]:
    lat, lng = (float(v) for v in s.split(","))
    return lat, lng


def load_frames(bq: data.QueryRunner, table: str, bucket: str, lat, lng, radius_m):
    sql = data.pano_meta_sql(table)
    params = data.pano_meta_params(lat=lat, lng=lng, radius_m=radius_m)
    print(f"dry run: {bq.dry_run(sql, params) / 1e9:.2f} GB (cap {data.HARD_MAX_BYTES / 1e9} GB)")
    frames = data.normalize_frames(bq.run(sql, params))
    frames["gcs_uri"] = [
        data.gcs_uri_for(bucket, s, o)
        for s, o in zip(frames["snapshot_id"], frames["observation_id"], strict=True)
    ]
    panos = sequence.build_sequences(data.panos_from_frames(frames))
    panos["travel_deg"] = sequence.travel_bearing(panos)
    return frames, panos


def save(out: Path, name: str, img) -> str:
    (out / "img").mkdir(parents=True, exist_ok=True)
    (out / "img" / name).write_bytes(images.encode_jpeg(img))
    return f"img/{name}"


def uc2_uc3(out, frames, panos, ids, intr, fetch):
    """Level views (UC2) and road views (UC3) for the selected panos."""
    level, road, rows = [], [], []
    by_pano = panos.set_index("pano_id")
    for pid in ids:
        prow = frames[frames["pano_id"] == pid].to_dict("records")
        for spec in pipeline.views_for_pano(prow, intr):
            img = images.decode(fetch(spec.gcs_uri))
            yaw = spec.view.yaw_deg
            path = save(out, f"uc2_{pid}_{round(yaw)}.jpg", pipeline.render_view(img, intr, spec))
            level.append({"image": path, "caption": f"{pid} yaw {yaw:.1f}"})
            rows.append(
                {"pano_id": pid, "observation_id": spec.observation_id, "view_yaw_deg": yaw}
            )
        travel = float(by_pano.loc[pid, "travel_deg"])
        for role in sequence.ROAD_VIEW_ROLES:
            rv = sequence.road_view(prow, intr, travel, role, pitch_deg=ROAD_VIEW_PITCH)
            if rv is None:
                continue
            img = images.decode(fetch(rv.choice.row["gcs_uri"]))
            path = save(out, f"uc3_{pid}_{role}.jpg", sequence.render_road_view(img, intr, rv))
            road.append({"image": path, "caption": f"{pid} {role}"})
    return level, road, labelkit.view_rows(rows)


def uc1_uc4(out, frames, panos, houses, intr, fetch, radius_m):
    """Every candidate view (UC1) and the roof views (UC4) of each target house."""
    frames = frames.merge(panos[["pano_id", "seq_id"]], on="pano_id", how="left")
    house_items, roof_items, rows = [], [], []
    for h in houses.itertuples():
        cands = views.house_view_candidates(
            frames, h.lat, h.lng, intr, aspect=HOUSE_VIEW[0] / HOUSE_VIEW[1], max_dist_m=radius_m
        )
        for c in views.rank_house_views(cands, max_per_seq=len(cands) or 1).to_dict("records"):
            view = views.view_for(c, *HOUSE_VIEW)
            pose, k = c["camera_pose"], int(c["cam_k"])
            if rosette.view_black_fraction(intr, pose, view, k) >= MAX_BLACK:
                continue
            img = images.decode(fetch(c["gcs_uri"]))
            name = f"uc1_{h.house_id}_{c['pano_id']}.jpg"
            path = save(out, name, rosette.render_perspective(img, intr, pose, view, k))
            house_items.append({"image": path, "caption": f"house {h.house_id} {c['pano_id']}"})
            rows.append({"label_id": f"H_{h.house_id}_{c['pano_id']}", "pano_id": c["pano_id"],
                         "view_yaw_deg": f"{view.yaw_deg:.1f}", "class": "HOUSE",
                         "object_key": f"house_{h.house_id}"})  # fmt: skip
        rv = views.rank_roof_views(
            frames, h.lat, h.lng, intr, aspect=ROOF_VIEW[0] / ROOF_VIEW[1], max_dist_m=radius_m
        )
        for r in rv.to_dict("records"):
            img = images.decode(fetch(r["gcs_uri"]))
            rimg, view, black = roof.render_roof_view(
                img, intr, r["camera_pose"], float(r["bearing"]), int(r["cam_k"]),
                pitch_deg=float(r["pitch"]), hfov_deg=float(r["hfov"]),
                width=ROOF_VIEW[0], height=ROOF_VIEW[1],
            )  # fmt: skip
            if black >= MAX_BLACK:
                continue
            path = save(out, f"uc4_{h.house_id}_{r['pano_id']}.jpg", rimg)
            roof_items.append({"image": path, "caption": f"roof {h.house_id} {r['pano_id']}"})
            rows.append({"label_id": f"R_{h.house_id}_{r['pano_id']}", "pano_id": r["pano_id"],
                         "view_yaw_deg": f"{view.yaw_deg:.1f}", "class": "ROOF_EDGE",
                         "object_key": f"house_{h.house_id}"})  # fmt: skip
    return house_items, roof_items, rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None, help="billing project (default: $PROJECT_ID)")
    ap.add_argument("--gcs-bucket", default=None, help="frame bucket (default: $GCS_BUCKET)")
    ap.add_argument("--dataset", default=config.DEFAULT_DATASET)
    ap.add_argument("--aoi", type=parse_latlng, action="append", required=True,
                    help="lat,lng of a neighbourhood (repeat; the protocol uses 2)")  # fmt: skip
    ap.add_argument("--n-panos", type=int, default=20)
    ap.add_argument("--radius-m", type=float, default=250.0)
    ap.add_argument("--houses", help="CSV with house_id,lat,lng (UC1/UC4 targets)")
    ap.add_argument("--house-radius-m", type=float, default=80.0)
    default_out = Path.home() / "svi_label_kit" / dt.date.today().isoformat()
    ap.add_argument("--out", type=Path, default=default_out)
    args = ap.parse_args()

    settings = config.resolve_settings(
        args.project, args.gcs_bucket, env=dict(os.environ), dataset=args.dataset
    )
    creds = auth.get_credentials()
    from google.cloud import storage

    bq = data.QueryRunner(
        data.make_bigquery_client(settings.project, creds),
        allowed_tables=data.pano_tables(settings.project, args.dataset),
        cache_dir=data.DEFAULT_QUERY_CACHE,
    )
    table = data.pano_table(settings.project, args.dataset)
    fetch = images.GcsImageFetcher(
        storage.Client(project=settings.project, credentials=creds)
    ).fetch
    intr = rosette.load_intrinsics()
    out = args.out.expanduser()
    out.mkdir(parents=True, exist_ok=True)

    level, road, rows, all_ids, frames_all, panos_all = [], [], [], [], [], []
    for lat, lng in args.aoi:
        frames, panos = load_frames(bq, table, settings.bucket, lat, lng, args.radius_m)
        ids = labelkit.consecutive_window(panos, lat, lng, args.n_panos)
        print(f"AOI {lat:.5f},{lng:.5f}: {len(panos)} panos; labelling {len(ids)} consecutive")
        lv, rd, vr = uc2_uc3(out, frames, panos, ids, intr, fetch)
        level, road, rows = level + lv, road + rd, rows + vr + labelkit.surface_slots(ids)
        all_ids += ids
        frames_all.append(frames)
        panos_all.append(panos)
    pages = {"uc2_level_views.html": ("UC2 level views: box every object", level),
             "uc3_road_views.html": ("UC3 road views: material, side, present", road)}  # fmt: skip
    if args.houses:
        houses = pd.read_csv(args.houses)
        frames = pd.concat(frames_all).drop_duplicates("observation_id")
        panos = pd.concat(panos_all).drop_duplicates("pano_id")
        hv, rv, hr = uc1_uc4(out, frames, panos, houses, intr, fetch, args.house_radius_m)
        rows += hr
        pages["uc1_house_views.html"] = ("UC1 candidate views: visible, centred, attributes", hv)
        pages["uc4_roof_views.html"] = ("UC4 roof views: trace every roof edge", rv)
    for name, (title, items) in pages.items():
        (out / name).write_text(labelkit.html_page(title, items))
    labelkit.write_label_sheet(out / "labels.csv", rows)
    second = labelkit.second_labeller_panos(all_ids)
    (out / "second_labeller_panos.txt").write_text("\n".join(second) + "\n")
    print(f"wrote {sum(len(i) for _, i in pages.values())} views and {len(rows)} label rows")
    print(f"kit: {out} (local only; do not commit or redistribute)")


if __name__ == "__main__":
    sys.exit(main())
