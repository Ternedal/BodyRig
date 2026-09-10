from bodyrig.photoidentity_target_crop_detail import (
    SUPPORTED_DOMAINS,
    analyze_openpose_target_crop,
    analyze_schp_target_crop,
)


def _triples(points: list[tuple[float, float, float]], count: int) -> list[float]:
    padded = points + [(0.0, 0.0, 0.0)] * (count - len(points))
    return [value for point in padded[:count] for value in point]


def test_openpose_target_crop_reports_only_observable_eye_hand_foot_candidates() -> None:
    body = [(0.0, 0.0, 0.0)] * 25
    body[19:22] = [(100.0, 500.0, 0.95), (180.0, 500.0, 0.94), (140.0, 560.0, 0.96)]
    body[22:25] = [(400.0, 500.0, 0.95), (480.0, 500.0, 0.94), (440.0, 560.0, 0.96)]
    left_hand = [(80.0 + i * 8.0, 300.0 + (i % 4) * 18.0, 0.94) for i in range(21)]
    right_hand = [(380.0 + i * 8.0, 300.0 + (i % 4) * 18.0, 0.93) for i in range(21)]
    face = [(0.0, 0.0, 0.0)] * 70
    face[36:42] = [(150.0 + i * 10.0, 140.0 + (i % 2) * 10.0, 0.95) for i in range(6)]
    face[42:48] = [(300.0 + i * 10.0, 140.0 + (i % 2) * 10.0, 0.96) for i in range(6)]
    payload = {"people": [{
        "pose_keypoints_2d": _triples(body, 25),
        "hand_left_keypoints_2d": _triples(left_hand, 21),
        "hand_right_keypoints_2d": _triples(right_hand, 21),
        "face_keypoints_2d": _triples(face, 70),
    }]}
    result = analyze_openpose_target_crop(payload, width=640, height=640)
    domains = {row["domain"] for row in result}
    assert domains == {"eyes_detail", "hands", "feet"}
    assert all(row["source_detail_quality_authority"] is False for row in result)
    assert all(row["photoidentity_sufficiency_authority"] is False for row in result)


def test_schp_target_crop_reports_only_hair_and_exposed_skin_candidates() -> None:
    seg = [[0 for _ in range(512)] for _ in range(512)]
    for y in range(40, 120):
        for x in range(180, 330):
            seg[y][x] = 2
    for y in range(105, 210):
        for x in range(200, 310):
            seg[y][x] = 11
    for y in range(220, 400):
        for x in range(70, 120):
            seg[y][x] = 14
        for x in range(390, 440):
            seg[y][x] = 15
    result = analyze_schp_target_crop(seg, source_width=1024, source_height=1024)
    assert {row["domain"] for row in result} == {"hair_hairline", "skin_detail"}
    assert all(row["source_detail_quality_authority"] is False for row in result)
    assert all(row["photoidentity_sufficiency_authority"] is False for row in result)


def test_target_crop_analyzers_have_no_anatomy_or_nail_domain_authority() -> None:
    assert SUPPORTED_DOMAINS == frozenset({"eyes_detail", "hands", "feet", "hair_hairline", "skin_detail"})
    assert not ({"body_rear", "torso_chest", "waist_hips", "fingernails_detail", "toenails_detail"} & SUPPORTED_DOMAINS)
