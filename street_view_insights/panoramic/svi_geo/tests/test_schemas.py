import pytest
from pydantic import ValidationError

from svi_geo import schemas


def test_detection_validates_box_and_confidence():
    d = schemas.Detection(label="UTILITY_POLE", box_2d=[100, 200, 900, 260], confidence=0.8)
    assert d.label is schemas.AssetClass.UTILITY_POLE
    for bad in ([0, 0, 0, 10], [10, 10, 5, 20], [0, 0, 10, 1001], [1, 2, 3]):
        with pytest.raises(ValidationError):
            schemas.Detection(label="HOUSE", box_2d=bad, confidence=0.5)
    with pytest.raises(ValidationError):
        schemas.Detection(label="HOUSE", box_2d=[0, 0, 10, 10], confidence=80)  # percent


def test_surface_taxonomy_has_turf_and_numeric_confidence():
    assert "Turf" in {m.value for m in schemas.SurfaceMaterial}
    r = schemas.SurfaceMaterialResult.model_validate_json(
        '{"primary_material": "Turf", "confidence": 0.7, "surface_condition": "Good",'
        ' "visual_reasoning": "grass"}'
    )
    assert r.primary_material is schemas.SurfaceMaterial.TURF


def test_box_2d_to_pixels():
    assert schemas.box_2d_to_pixels([100, 250, 500, 750], 1000, 2000) == (250, 200, 750, 1000)


def test_roof_edge_points_validated():
    with pytest.raises(ValidationError):
        schemas.RoofEdge(edge_type="RIDGE", points=[[10, 10]])
    e = schemas.RoofEdge(edge_type="EAVE", points=[[10, 10], [20, 900]])
    assert e.edge_type is schemas.EdgeType.EAVE


def test_presence_check_optional_box():
    assert schemas.PresenceCheck(present=False, confidence=0.9).box_2d is None


def test_attribute_enums_constrain_free_text():
    d = schemas.Detection(
        label="UTILITY_POLE", box_2d=[1, 2, 3, 4], confidence=0.5, material="WOOD"
    )
    assert d.material is schemas.AssetMaterial.WOOD
    with pytest.raises(ValidationError):
        schemas.Detection(
            label="UTILITY_POLE", box_2d=[1, 2, 3, 4], confidence=0.5, material="Wood"
        )
    h = schemas.HouseView(
        house_visible=True,
        occlusion="NONE",
        facade_visible_fraction=0.8,
        exterior_material="BRICK",
        roof_type="GABLE",
        confidence=0.9,
    )
    assert h.roof_type is schemas.RoofType.GABLE
    assert h.exterior_material is schemas.ExteriorMaterial.BRICK
    assert "UNKNOWN" in schemas.RoofType.__members__


def test_frame_detections_repairs_or_drops_bad_boxes_instead_of_failing():
    raw = {
        "detections": [
            {"label": "HOUSE", "box_2d": [100, 100, 500, 600], "confidence": 0.9},
            {"label": "HOUSE", "box_2d": [500, 600, 100, 100], "confidence": 0.8},  # swapped
            {"label": "HOUSE", "box_2d": [100, 100, 100, 600], "confidence": 0.8},  # degenerate
            {"label": "ROAD_SIGN", "box_2d": [1, 2, 3], "confidence": 0.8},  # malformed
        ]
    }
    fd = schemas.FrameDetections.model_validate(raw)
    assert [d.box_2d for d in fd.detections] == [[100, 100, 500, 600], [100, 100, 500, 600]]
    assert fd.n_dropped == 2
    assert "n_dropped" not in schemas.FrameDetections.model_json_schema()["properties"]


# ----------------------------------------------------------------------------- in-image checks


def _house(box, visible=True):
    return schemas.HouseView(
        house_visible=visible, box_2d=box, occlusion="NONE", facade_visible_fraction=0.5,
        confidence=0.8,
    )  # fmt: skip


def test_house_view_accepts_a_real_box_and_no_box():
    _house([100, 200, 600, 800]).validate_in_image(1024, 768)
    _house(None, visible=False).validate_in_image(1024, 768)


def test_house_view_rejects_a_box_thinner_than_two_pixels():
    with pytest.raises(ValueError, match="degenerate"):
        _house([100, 500, 900, 501]).validate_in_image(1024, 768)  # 1 unit = 1 px wide


def test_house_view_rejects_out_of_range_box_even_if_constructed_unchecked():
    h = schemas.HouseView.model_construct(
        house_visible=True, box_2d=[0, 0, 500, 1200], occlusion="NONE",
        facade_visible_fraction=0.5, confidence=0.8,
    )  # fmt: skip
    with pytest.raises(ValueError, match="0..1000"):
        h.validate_in_image(1024, 768)


def _roof(*polylines):
    return schemas.RoofEdges.model_construct(
        roof_visible=True,
        edges=[schemas.RoofEdge.model_construct(edge_type="EAVE", points=p) for p in polylines],
        confidence=0.7,
    )


def test_roof_edges_accept_a_clean_polyline():
    _roof([[100, 100], [100, 900]], [[100, 900], [400, 950], [700, 990]]).validate_in_image(
        1200, 900
    )


@pytest.mark.parametrize(
    "bad, why",
    [
        ([[100, 100]], "2 points"),
        ([], "2 points"),
        ([[100, 100], [100, 100]], "repeated"),
        ([[100, 100], [300, 300], [100, 100]], "repeated"),
        ([[100, 100], [100, 1001]], "0..1000"),
        ([[-1, 100], [100, 200]], "0..1000"),
    ],
)
def test_roof_edges_reject_bad_polylines(bad, why):
    with pytest.raises(ValueError, match=why):
        _roof([[10, 10], [10, 500]], bad).validate_in_image(1200, 900)


def test_roof_edges_reject_points_that_collapse_to_one_pixel():
    # 0.5 units apart after rounding to pixels at 400 px width -> the same pixel
    with pytest.raises(ValueError, match="repeated"):
        _roof([[500, 500], [500, 501]]).validate_in_image(400, 300)
