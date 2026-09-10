from __future__ import annotations

MODEL_REPOSITORY = "pirocheto/schp-atr-18"
MODEL_REVISION = "a54fa65e7e4f27f21011f652ffc0053ebb24b292"
MODEL_FILE = "onnx/schp-atr-18-int8-static.onnx"
MODEL_SHA256 = "4420d8db8c1f266967c89485786b01209f6d405f320fc0f87e8ced49392cefb5"
MODEL_SIZE = 69_141_996
MODEL_URL = (
    "https://huggingface.co/pirocheto/schp-atr-18/resolve/"
    f"{MODEL_REVISION}/{MODEL_FILE}?download=true"
)
UPSTREAM_REPOSITORY = "GoGoDuck912/Self-Correction-Human-Parsing"
UPSTREAM_REVISION = "eb84c432cc697f494d99662a05f2335eb2f26095"
UPSTREAM_LICENSE = "MIT"
TRAINING_DATASET = "ATR"
TRAINING_DATASET_USE_NOTE = (
    "Original HumanParsing-Dataset README explicitly requests citation for academic and commercial research; "
    "BodyRig does not redistribute the ATR dataset or SCHP pretrained weights."
)

ADAPTER = "schp-atr18-source-observability"
ADAPTER_REVISION = "1"
CAPABILITIES = ("hair-detail", "skin-detail")
INPUT_NAME = "pixel_values"
OUTPUT_NAME = "logits"
INPUT_SIZE = (512, 512)
LABELS = {
    0: "Background",
    1: "Hat",
    2: "Hair",
    3: "Sunglasses",
    4: "Upper-clothes",
    5: "Skirt",
    6: "Pants",
    7: "Dress",
    8: "Belt",
    9: "Left-shoe",
    10: "Right-shoe",
    11: "Face",
    12: "Left-leg",
    13: "Right-leg",
    14: "Left-arm",
    15: "Right-arm",
    16: "Bag",
    17: "Scarf",
}
IMAGE_MEAN = (0.406, 0.456, 0.485)
IMAGE_STD = (0.225, 0.224, 0.229)

# Intentional authority boundary: ATR parsing is a fashion-oriented semantic
# segmenter. It can prove that hair and exposed face/limb skin are observable;
# it cannot prove subject-specific anatomy, rear orientation or nail surfaces.
UNSUPPORTED_IDENTITY_DOMAINS = (
    "body_rear",
    "torso_chest",
    "waist_hips",
    "fingernails_detail",
    "toenails_detail",
)
