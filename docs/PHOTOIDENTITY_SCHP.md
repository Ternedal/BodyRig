# Photoidentity SCHP source observability

BodyRig uses SCHP/ATR only as a bounded, source-derived observability analyzer for the photoidentity sufficiency gate.

Authority is intentionally narrow:

- `hair-detail`: may contribute only to `hair_hairline` when a real Hair mask is adjacent to a real Face mask and source-space extent/quality thresholds pass. In BodyRig, `hair_hairline` means **scalp/head hair and the facial hairline only**.
- `skin-detail`: may contribute only to `skin_detail` when exposed face plus multiple independently segmented limb regions are observable at sufficient source quality.

The SCHP/ATR Hair class does **not** give BodyRig authority for eyebrows, beard/moustache or other facial hair, chest/abdomen/limb hair, pubic hair, or other body hair. Those identity dimensions are represented separately as `eyebrows_detail`, `facial_hair_detail`, and `body_hair_detail`. They can only enter photoidentity authority through explicit human review of an already human-isolated, hash-bound source crop. The human review may attest a visible no-hair/clean-shaven state; absence of hair is not treated as absence of evidence when the relevant region is actually visible at sufficient source quality.

For the target-crop quality CLI, machine-assisted domains retain the existing `<sample>:<domain>` form. Human-only hair domains require an explicit reviewed quality in `<sample>:<domain>:<0..1>` form, for example `targetsample-0001:eyebrows_detail:0.92`. The canonical detail threshold remains `0.80`; the score is recorded as human-reviewed source quality and is never relabeled as machine observability.

SCHP/ATR also has **no authority** to prove subject-specific anatomy, rear orientation, breasts/torso shape, waist/hips shape, fingernails or toenails. Those remain separate blockers until purpose-built source evidence exists.

The runtime is isolated from BodyRig's normal Python environment. The model is not redistributed by BodyRig; setup downloads the exact pinned model and verifies SHA-256 before a create-only runtime receipt can exist. Every inference revalidates the pinned model bytes and runtime contract.

Current pins:

- upstream SCHP repository: `GoGoDuck912/Self-Correction-Human-Parsing`
- upstream revision: `eb84c432cc697f494d99662a05f2335eb2f26095`
- upstream code license: MIT
- model repository: `pirocheto/schp-atr-18`
- model revision: `a54fa65e7e4f27f21011f652ffc0053ebb24b292`
- model file: `onnx/schp-atr-18-int8-static.onnx`
- model SHA-256: `4420d8db8c1f266967c89485786b01209f6d405f320fc0f87e8ced49392cefb5`

The original ATR dataset README explicitly asks users to cite it for academic and commercial research, but does not provide a standalone LICENSE file. For that reason BodyRig does not vendor or redistribute the pretrained weight file or ATR dataset.

This analyzer does not grant production activation and does not permit generic guessing.
