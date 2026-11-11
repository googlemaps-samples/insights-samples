# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""3D LiDAR spatial utilities for both Full-Frame and Panoramic Street View Insights."""

from .io_and_frames import (
    GPS_TO_UNIX_OFFSET_SEC,
    WGS84_A,
    WGS84_E2,
    build_observation_lidar_sql,
    build_pano_rosette_lidar_sql,
    deduplicate_enu_voxels,
    ecef_to_enu,
    enu_to_camera,
    enu_to_ecef,
    fetch_observation_and_laz_metadata,
    infer_lidar_mode,
    lla_to_ecef,
    parse_pano_observation_id,
    select_pano_rosette_laz_and_cameras,
    select_same_pass_laz_rows,
    stream_and_merge_laz_enu,
    stream_laz_from_gcs,
)
from .measurements_3d import (
    discover_roadside_assets_3d,
    estimate_local_ground_z,
    measure_corridor_cross_section,
    measure_facade_3d,
    measure_point_to_point_3d,
    measure_pole_3d,
    measure_sign_3d,
    measure_tree_3d,
)
from .multimodal_fusion import (
    VEHICLE_CLEARANCE_PROFILES,
    analyze_building_and_driveway_scene,
    build_depth_gated_crop,
    cast_2d_box_to_3d_cluster,
    classify_depth_gated_crop_with_gemini,
)
from .projection_and_rgb import (
    DISTORTION_K1,
    DISTORTION_K2,
    FOCAL_LENGTH_PX,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    LENS_FOV_DEG,
    MIN_EGO_CLEARANCE_M,
    PITCH_BIAS_DEG,
    PRINCIPAL_X,
    PRINCIPAL_Y,
    colorize_multiview_point_cloud,
    colorize_points_zbuffer,
    export_colored_ply,
    filter_front_surface_overlay,
    project_cam_to_uv,
    project_points_to_image,
)

__all__ = [
    "DISTORTION_K1",
    "DISTORTION_K2",
    "FOCAL_LENGTH_PX",
    "GPS_TO_UNIX_OFFSET_SEC",
    "IMAGE_HEIGHT",
    "IMAGE_WIDTH",
    "LENS_FOV_DEG",
    "MIN_EGO_CLEARANCE_M",
    "PITCH_BIAS_DEG",
    "PRINCIPAL_X",
    "PRINCIPAL_Y",
    "VEHICLE_CLEARANCE_PROFILES",
    "WGS84_A",
    "WGS84_E2",
    "analyze_building_and_driveway_scene",
    "build_depth_gated_crop",
    "build_observation_lidar_sql",
    "build_pano_rosette_lidar_sql",
    "cast_2d_box_to_3d_cluster",
    "classify_depth_gated_crop_with_gemini",
    "colorize_multiview_point_cloud",
    "colorize_points_zbuffer",
    "deduplicate_enu_voxels",
    "discover_roadside_assets_3d",
    "ecef_to_enu",
    "enu_to_camera",
    "enu_to_ecef",
    "estimate_local_ground_z",
    "export_colored_ply",
    "fetch_observation_and_laz_metadata",
    "filter_front_surface_overlay",
    "infer_lidar_mode",
    "lla_to_ecef",
    "measure_corridor_cross_section",
    "measure_facade_3d",
    "measure_point_to_point_3d",
    "measure_pole_3d",
    "measure_sign_3d",
    "measure_tree_3d",
    "parse_pano_observation_id",
    "project_cam_to_uv",
    "project_points_to_image",
    "select_pano_rosette_laz_and_cameras",
    "select_same_pass_laz_rows",
    "stream_and_merge_laz_enu",
    "stream_laz_from_gcs",
]
