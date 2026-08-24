from __future__ import annotations

import pytest

from bodyrig.portable_identity import PortableIdentityError, validate_portable_identity


def test_boolean_version_is_rejected_as_non_v1() -> None:
    receipt = {
        "format": "bodyrig-portable-identity",
        "version": True,
        "body_id": "bodyid-000000000000000000000000",
        "requested_alias": "performer-123",
        "source_count": 1,
        "source_set_sha256": "1" * 64,
        "recovery_proof_sha256": "2" * 64,
        "visual_identity_sha256": "3" * 64,
        "subject_track_id": "7",
        "authority": {"adapter": "bodyrig.portable_identity", "revision": "1"},
    }

    with pytest.raises(PortableIdentityError, match="format/version"):
        validate_portable_identity(receipt)
