from bodyrig.preflight_cli import SMPL_FILENAME
from bodyrig.bridges.hmr2_config import FOUR_D_HUMANS_REVISION, PHALP_TRACKER_BLOB_SHA1


def test_preflight_pins_concrete_upstream_identities():
    assert len(FOUR_D_HUMANS_REVISION) == 40
    assert len(PHALP_TRACKER_BLOB_SHA1) == 40
    assert SMPL_FILENAME.endswith(".pkl")
