# BodyRig V1 architecture

## Responsibility

BodyRig is an embodiment/motor system, not another assistant brain.

```text
ModelRig: reasoning + semantic intent
VoiceRig: audio input/output + utterance timing
BodyRig: body identity + expression/motion realization
Kaliv/VR: presentation/rendering
```

ModelRig sends meaning, not joint rotations. A cue such as `small_shrug` is mapped through the selected body's own motion profile, so two bodies may realize the same semantic cue differently.

## Build path

```text
1–10 videos
  -> normalize/sample
  -> person detection/tracking
  -> isolated 3D body recovery engine
  -> canonical timestamped named 3D joints
  -> BodyprintExtractor
  -> avatar fitting/rigging
  -> VRM 1.0 export
  -> .mrbody
```

The recovery process is isolated because research engines and SMPL-family assets may have incompatible Python/Torch stacks and separate license terms. Completed `.mrbody` profiles must animate without the recovery environment.

## Runtime path

```text
ModelRig ---- BodyCue(utterance_id) ----+
                                        v
                                    BodyRig
                                        ^
VoiceRig --- speech/viseme timing -------+
```

Speech timing with a different `utterance_id` is rejected, preventing stale lipsync/body motion from attaching to a newer answer.

## V1 acceptance direction

V1 is not production-ready until real input video proves: correct subject tracking, recognizable source-derived proportions, multiple personalized motion metrics, valid VRM output, synchronized VoiceRig playback and loading in both Windows and Android/Quest-class reference renderers.
