from __future__ import annotations

from .hmr2_config import PHALP_REVISION

DETECTRON2_REVISION = "a2f4a8771ab77e8411c26b27f24f9489a28a2453"
DETECTRON2_CONFIG = "new_baselines/mask_rcnn_regnety_4gf_dds_FPN_400ep_LSJ.py"
DETECTRON2_CHECKPOINT_URL = (
    "https://dl.fbaipublicfiles.com/detectron2/"
    "new_baselines/mask_rcnn_regnety_4gf_dds_FPN_400ep_LSJ/"
    "42045954/model_final_ef3a80.pkl"
)
DETECTRON2_CHECKPOINT_BYTES = 167_792_431
DETECTRON2_CHECKPOINT_SHA256 = "268819eb7419a02b2a9bcb510a4cb06c2b33a534897f7351871295b544eeb05e"
MASK_ADAPTER = "phalp-detectron2-person-instance-mask"
MASK_REVISION = (
    f"phalp:{PHALP_REVISION};"
    f"d2:{DETECTRON2_REVISION};"
    f"weights:{DETECTRON2_CHECKPOINT_SHA256}"
)
