from __future__ import annotations

from bodyrig.stash_performer_profile import body_model_gender, fetch_performer_profile
from bodyrig.stash_source import StashConfig


class _Client:
    def __init__(self, item=None, error=None):
        self.item = item
        self.error = error

    def _graphql(self, query, variables):
        if self.error is not None:
            raise self.error
        assert "gender" in query
        assert "eye_color" in query
        assert "hair_color" in query
        assert "height_cm" in query
        return {"findPerformer": self.item}

    def performer(self, performer_id):
        return {"id": performer_id, "name": "Legacy", "disambiguation": ""}


def test_stash_gender_maps_to_smplx_model() -> None:
    assert body_model_gender("FEMALE") == "female"
    assert body_model_gender("TRANSGENDER_FEMALE") == "female"
    assert body_model_gender("MALE") == "male"
    assert body_model_gender("TRANSGENDER_MALE") == "male"
    assert body_model_gender("INTERSEX") == "neutral"
    assert body_model_gender("NON_BINARY") == "neutral"
    assert body_model_gender(None) == "neutral"
    assert body_model_gender("future-value") == "neutral"


def test_profile_exposes_model_gender_and_appearance_metadata() -> None:
    profile = fetch_performer_profile(
        _Client(
            item={
                "id": "42",
                "name": "Example",
                "disambiguation": "",
                "gender": "FEMALE",
                "eye_color": "Blue",
                "hair_color": "Blonde",
                "height_cm": 178,
            }
        ),
        "42",
    )
    assert profile == {
        "id": "42",
        "name": "Example",
        "disambiguation": "",
        "stash_gender": "FEMALE",
        "body_model_gender": "female",
        "gender_source": "stash-performer-metadata",
        "eye_color": "Blue",
        "hair_color": "Blonde",
        "height_cm": 178,
        "profile_query_error": "",
    }


def test_stash_config_still_does_not_serialize_api_key() -> None:
    config = StashConfig(url="http://127.0.0.1:9999", api_key="secret")
    assert "secret" not in repr({"url": config.url, "timeout": config.timeout_seconds})
