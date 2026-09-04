from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Mapping

from .stash_source import StashClient, StashConfig, StashGraphQLError, StashSourceError

STASH_TO_SMPLX_GENDER = {
    "FEMALE": "female",
    "TRANSGENDER_FEMALE": "female",
    "MALE": "male",
    "TRANSGENDER_MALE": "male",
    "INTERSEX": "neutral",
    "NON_BINARY": "neutral",
}
SMPLX_GENDERS = ("female", "male", "neutral")


class PerformerProfileError(StashSourceError):
    pass


def body_model_gender(stash_gender: Any) -> str:
    value = str(stash_gender or "").strip().upper()
    return STASH_TO_SMPLX_GENDER.get(value, "neutral")


def fetch_performer_profile(client: StashClient, performer_id: str) -> dict[str, Any]:
    performer_id = str(performer_id).strip()
    if not performer_id:
        raise PerformerProfileError("performer id is required")

    query = """
query BodyRigPerformerProfile($id: ID!) {
  findPerformer(id: $id) {
    id
    name
    disambiguation
    gender
    eye_color
    hair_color
    height_cm
  }
}
"""
    try:
        data = client._graphql(query, {"id": performer_id})
    except StashGraphQLError as exc:
        # Do not silently guess a sex-specific model when the installed Stash
        # schema cannot expose performer gender. A neutral model is the only
        # safe automatic fallback; callers can provide an explicit reviewed
        # override at the production launcher boundary.
        base = client.performer(performer_id)
        return {
            "id": str(base["id"]),
            "name": str(base["name"]),
            "disambiguation": str(base.get("disambiguation") or ""),
            "stash_gender": "",
            "body_model_gender": "neutral",
            "gender_source": "schema-fallback-neutral",
            "eye_color": "",
            "hair_color": "",
            "height_cm": None,
            "profile_query_error": str(exc)[:500],
        }

    item = data.get("findPerformer")
    if not isinstance(item, Mapping) or not item.get("id") or not item.get("name"):
        raise PerformerProfileError(f"Stash performer not found: {performer_id}")

    stash_gender = str(item.get("gender") or "").strip().upper()
    resolved_gender = body_model_gender(stash_gender)
    height_raw = item.get("height_cm")
    height_cm: int | None
    if height_raw is None:
        height_cm = None
    else:
        try:
            height_cm = int(height_raw)
        except (TypeError, ValueError) as exc:
            raise PerformerProfileError("Stash performer height_cm is not an integer") from exc
        if not 50 <= height_cm <= 300:
            height_cm = None

    return {
        "id": str(item["id"]),
        "name": str(item["name"]),
        "disambiguation": str(item.get("disambiguation") or ""),
        "stash_gender": stash_gender,
        "body_model_gender": resolved_gender,
        "gender_source": "stash-performer-metadata" if stash_gender else "stash-metadata-missing-neutral",
        "eye_color": str(item.get("eye_color") or "").strip(),
        "hair_color": str(item.get("hair_color") or "").strip(),
        "height_cm": height_cm,
        "profile_query_error": "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve Stash performer metadata used by BodyRig fitting.")
    parser.add_argument("--performer-id", required=True)
    parser.add_argument("--url", default="")
    parser.add_argument("--api-key-env", default="STASH_API_KEY")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args(argv)

    try:
        url = (args.url or os.environ.get("STASH_URL") or "").strip()
        if not url:
            raise PerformerProfileError("Stash URL is required via --url or STASH_URL")
        api_key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
        client = StashClient(StashConfig(url=url, api_key=api_key, timeout_seconds=args.timeout))
        profile = fetch_performer_profile(client, args.performer_id)
    except StashSourceError as exc:
        print(f"BodyRig Stash performer profile: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(profile, separators=(",", ":"), ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
