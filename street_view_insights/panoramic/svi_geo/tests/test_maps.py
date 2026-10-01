"""Unit tests for svi_geo/maps.py and attribution.save_figure (Tasks U10 & U12)."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from svi_geo import attribution, maps


def _sample_rosettes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "capture_id": "cap_01",
                "pano_id": "pano_01",
                "snapshot_id": "snap_01",
                "seq_id": "snap_01_0",
                "seq_idx": 1,
                "lat": 28.0501,
                "lng": -81.9601,
                "wkt": "POINT(-81.9601 28.0501)",
                "travel_deg": 0,
                "map_url": "https://www.google.com/maps/@?api=1&map_action=pano&pano=pano_01",
            },
            {
                "capture_id": "cap_02",
                "pano_id": None,
                "snapshot_id": "snap_01",
                "seq_id": "snap_01_0",
                "seq_idx": 2,
                "lat": 28.0502,
                "lng": -81.9601,
                "wkt": "POINT(-81.9601 28.0502)",
                "travel_deg": 0,
                "map_url": "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=28.0502,-81.9601",
            },
        ]
    )


def test_parse_wkt_point_extracts_lat_lng():
    lat, lng = maps.parse_wkt_point("POINT(-81.96015 28.05047)")
    assert abs(lat - 28.05047) < 1e-6
    assert abs(lng - (-81.96015)) < 1e-6


def test_maps_helper_adds_attribution(tmp_path):
    ros = _sample_rosettes()
    m_tracks = maps.rosette_tracks_map(ros, out_path=tmp_path / "tracks.html")
    html_tracks = m_tracks.get_root().render()
    assert attribution.IMAGERY_CREDIT in html_tracks
    assert (tmp_path / "tracks.html").is_file()

    m_uc1 = maps.uc1_house_map(
        ros,
        target_lat=28.0504,
        target_lng=-81.9599,
        out_path=tmp_path / "uc1_map.html",
    )
    assert attribution.IMAGERY_CREDIT in m_uc1.get_root().render()
    assert (tmp_path / "uc1_map.html").is_file()

    ent_df = pd.DataFrame(
        [
            {
                "entity_id": "UTILITY_POLE_01",
                "class": "UTILITY_POLE",
                "lat": 28.05015,
                "lng": -81.96005,
                "method": "triangulated",
                "n_panos": 2,
                "rms_m": 0.4,
                "confidence": 0.9,
            }
        ]
    )
    m_uc2 = maps.uc2_entities_map(ros, ent_df, out_path=tmp_path / "uc2_map.html")
    assert attribution.IMAGERY_CREDIT in m_uc2.get_root().render()

    slot_rows = [
        {
            "asset": "ROAD",
            "side": "CENTER",
            "segments": [
                {
                    "label": "Paved Asphalt",
                    "points": [(28.0501, -81.9601), (28.0502, -81.9601)],
                    "length_m": 11.1,
                }
            ],
        }
    ]
    m_uc3 = maps.uc3_segments_map(ros, slot_rows, out_path=tmp_path / "uc3_map.html")
    assert attribution.IMAGERY_CREDIT in m_uc3.get_root().render()

    m_uc4 = maps.uc4_roof_map(
        ros, target_lat=28.0504, target_lng=-81.9599, out_path=tmp_path / "uc4_map.html"
    )
    assert attribution.IMAGERY_CREDIT in m_uc4.get_root().render()


def test_save_figure_stamps_attribution_and_writes_png(tmp_path):
    fig, ax = plt.subplots(figsize=(4, 3))
    ax.plot([0, 1], [0, 1])
    out_png = attribution.save_figure(fig, tmp_path / "test_fig.png")
    plt.close(fig)
    assert out_png.is_file()
    assert out_png.stat().st_size > 500
