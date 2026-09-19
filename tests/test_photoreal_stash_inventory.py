from __future__ import annotations

from bodyrig.photoreal_stash_inventory import _projection_metadata, fetch_photoreal_source_inventory
from bodyrig.stash_source import StashClient, StashConfig


def _transport(query: str, variables: dict[str, object]) -> dict[str, object]:
    if "BodyRigStashVersion" in query:
        return {"version": {"version": "0.31.0"}}
    if "BodyRigPerformer($id" in query:
        return {"findPerformer": {"id": "42", "name": "Performer 42", "disambiguation": ""}}
    if "BodyRigPhotoidentityPerformerScenes" in query:
        return {
            "findScenes": {
                "count": 2,
                "scenes": [
                    {
                        "id": "s1",
                        "title": "8K SBS",
                        "files": [
                            {
                                "path": "E:/stash/8k-sbs.mp4",
                                "basename": "8k-sbs.mp4",
                                "width": 7680,
                                "height": 3840,
                                "duration": 3600.0,
                                "frame_rate": 60.0,
                                "video_codec": "h265",
                                "size": 1000,
                            }
                        ],
                        "tags": [{"name": "VR180"}, {"name": "SBS"}],
                        "performers": [{"id": "42", "name": "Performer 42"}],
                    },
                    {
                        "id": "s2",
                        "title": "4K flat",
                        "files": [
                            {
                                "path": "E:/stash/4k-flat.mp4",
                                "basename": "4k-flat.mp4",
                                "width": 3840,
                                "height": 2160,
                                "duration": 1800.0,
                                "frame_rate": 30.0,
                                "video_codec": "h264",
                                "size": 800,
                            }
                        ],
                        "tags": [],
                        "performers": [{"id": "42", "name": "Performer 42"}],
                    },
                ],
            }
        }
    if "BodyRigPhotorealGalleries" in query:
        return {
            "findGalleries": {
                "count": 1,
                "galleries": [
                    {
                        "id": "g1",
                        "title": "High res photos",
                        "date": None,
                        "details": None,
                        "photographer": None,
                        "image_count": 2,
                        "files": [],
                        "tags": [{"name": "Studio"}],
                        "performers": [{"id": "42", "name": "Performer 42"}],
                    }
                ],
            }
        }
    if "BodyRigPhotorealImages" in query:
        image_id = str(variables["id"])
        if image_id == "42":
            return {
                "findImages": {
                    "count": 1,
                    "images": [
                        {
                            "id": "i1",
                            "title": "Direct portrait",
                            "date": None,
                            "details": None,
                            "photographer": None,
                            "visual_files": [
                                {
                                    "__typename": "ImageFile",
                                    "id": "f1",
                                    "path": "F:/stash/portrait.jpg",
                                    "basename": "portrait.jpg",
                                    "width": 6000,
                                    "height": 4000,
                                    "size": 1234,
                                    "format": "jpeg",
                                }
                            ],
                            "tags": [],
                            "performers": [{"id": "42", "name": "Performer 42"}],
                            "galleries": [],
                        }
                    ],
                }
            }
        if image_id == "g1":
            return {
                "findImages": {
                    "count": 1,
                    "images": [
                        {
                            "id": "i2",
                            "title": "Gallery only",
                            "date": None,
                            "details": None,
                            "photographer": None,
                            "visual_files": [
                                {
                                    "__typename": "ImageFile",
                                    "id": "f2",
                                    "path": "F:/stash/gallery-only.png",
                                    "basename": "gallery-only.png",
                                    "width": 5000,
                                    "height": 3333,
                                    "size": 2345,
                                    "format": "png",
                                }
                            ],
                            "tags": [],
                            "performers": [],
                            "galleries": [
                                {
                                    "id": "g1",
                                    "title": "High res photos",
                                    "performers": [{"id": "42"}],
                                }
                            ],
                        }
                    ],
                }
            }
    raise AssertionError(query)


def test_photoreal_inventory_keeps_spatial_video_and_gallery_images() -> None:
    client = StashClient(StashConfig("http://stash.local:9998"), transport=_transport)

    result = fetch_photoreal_source_inventory(client, "42")

    assert result["format"] == "bodyrig-photoreal-source-inventory"
    assert result["performer_id"] == "42"
    assert result["performer_name"] == "Performer 42"
    assert result["performer"]["id"] == result["performer_id"]
    assert result["scene_count"] == 2
    assert result["video_file_count"] == 2
    assert result["gallery_count"] == 1
    assert result["image_file_count"] == 2
    assert result["summary"]["source_universe_exhaustive"] is True
    assert result["summary"]["flat_video_hours"] == 0.5
    assert result["summary"]["spatial_or_projection_video_hours"] == 1.0
    assert result["videos"][0]["projection"] == "vr180"
    assert result["videos"][0]["stereo_layout"] == "side-by-side"
    flat = next(item for item in result["videos"] if item["path"].endswith("4k-flat.mp4"))
    assert flat["projection"] == "flat"
    assert flat["stereo_layout"] == "mono"
    assert {item["source_binding"] for item in result["images"]} == {
        "direct-performer",
        "performer-gallery",
    }
    assert result["build_only"] is True
    assert result["photoreal_teacher_input"] is True
    assert result["runtime_dependency"] is False
    assert result["production_activation"] is False



def test_projection_metadata_treats_lowres_two_to_one_as_ambiguous() -> None:
    projection, stereo = _projection_metadata([], width=1920, height=960)

    assert projection == "projection-ambiguous-2to1"
    assert stereo == "unknown"


def test_projection_metadata_recognizes_degree_symbol_vr180_hint() -> None:
    projection, stereo = _projection_metadata(
        ["180°", "3D Available"],
        width=1920,
        height=960,
    )

    assert projection == "vr180"
    assert stereo == "mono"


def test_projection_metadata_keeps_standard_flat_widescreen_flat() -> None:
    projection, stereo = _projection_metadata([], width=3840, height=2160)

    assert projection == "flat"
    assert stereo == "mono"
