# BodyRig Motor State v1

ModelRig owns **what** the assistant means to express. BodyRig owns **how this body performs it**.

The boundary is therefore deliberately two-stage:

```text
ModelRig BodyCue
    semantic: thoughtful + small_shrug + gaze=user
                     |
                     v
               BodyRig runtime
               + active BodyPrint
                     |
                     v
BodyRig Motor State
    performed gesture amplitude, head motion, gaze strength, speech motion
                     |
                     v
              renderer / Kaliv / VR
```

A renderer must not need the original recovery model or source videos.

## Why a Motor State exists

If two cloned bodies receive the same ModelRig cue, they should not move identically.

A restrained BodyPrint may have low observed gesture amplitude and head motion. An expressive BodyPrint may have high values. `resolve_motor_state` combines the requested semantic intensity with those observed characteristics.

The renderer still owns engine-specific animation details such as Unity bone rotations or animation clips. BodyRig does **not** expose raw bone transforms as the ModelRig integration contract.

## Example

Input cue:

```json
{
  "type": "modelrig-body-cue",
  "version": 1,
  "utterance_id": "u-42",
  "emotion": "amused",
  "intensity": 0.6,
  "energy": 0.5,
  "gesture": "small_shrug",
  "gaze": "user"
}
```

Resolved output:

```json
{
  "type": "bodyrig-motor-state",
  "version": 1,
  "body_id": "person-a",
  "utterance_id": "u-42",
  "motion": {
    "energy": 0.58,
    "head_motion": 0.73
  },
  "expression": {
    "emotion": "amused",
    "intensity": 0.6
  },
  "gesture": {
    "id": "small_shrug",
    "amplitude": 0.79
  },
  "gaze": {
    "target": "user",
    "strength": 0.77
  }
}
```

The exact numeric example is illustrative. The runtime values are deterministic from the current cue and active BodyPrint.

## VoiceRig synchronization

VoiceRig timing is accepted only when `utterance_id` matches the active BodyCue. Motor State may then include:

- speech state;
- elapsed time;
- current viseme;
- amplitude resolved through the BodyPrint's speech-motion expressivity.

A stale VoiceRig event from a previous utterance is rejected rather than applied to the new body response.

## Body switches

Activating another `.mrbody` is a runtime session boundary. BodyRig clears:

- active utterance;
- current BodyCue;
- speech timing.

This prevents an animation or viseme from the previous body/profile leaking into the newly activated one.

## API

After a body is active and a BodyCue has been received:

```text
GET /api/v1/runtime/motor-state
```

returns `bodyrig-motor-state` v1.

Before those prerequisites exist the endpoint returns conflict rather than synthesizing identity/style values without a BodyPrint.

The machine-readable contract is `contracts/bodyrig-motor-state-v1.schema.json`.
