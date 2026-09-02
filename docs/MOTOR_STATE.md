# BodyRig Motor State v1 + v2

ModelRig owns **what** the assistant means to express. BodyRig owns **how this body performs it**.

The boundary is deliberately two-stage:

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

## Motor State v1

Motor State v1 is the compatibility contract. Its performed values are already personalized by BodyRig against the active BodyPrint.

Example:

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

The exact numeric example is illustrative. Runtime values are deterministic from the current cue and active BodyPrint.

## Motor State v2

Motor State v2 preserves the performed state and adds an optional `embodiment` receipt containing only physical-style values that were actually present in the active BodyPrint.

```json
{
  "type": "bodyrig-motor-state",
  "version": 2,
  "body_id": "person-a",
  "utterance_id": "u-42",
  "motion": {
    "energy": 0.58,
    "head_motion": 0.73
  },
  "gesture": {
    "id": "small_shrug",
    "amplitude": 0.79
  },
  "gaze": {
    "target": "user",
    "strength": 0.77
  },
  "embodiment": {
    "source": "modelrig-bodyprint-v1",
    "observed": {
      "gesture_frequency": 0.57,
      "turn_speed": 0.42,
      "walk_cadence_spm": 112.0
    }
  }
}
```

The receipt is evidence, not a second personalization pass. A renderer must not multiply `embodiment.observed.gesture_amplitude`, `head_motion`, `gaze_strength`, `speech_motion`, or other observations into the already-resolved performed values again. It must also not create a gesture, gait event, expression, or semantic action solely because an observed BodyPrint field exists.

The reference Unity renderer therefore accepts both Motor State v1 and v2, validates the v2 evidence source/ranges when present, and renders the same performed gesture/head/gaze/speech values for an otherwise equivalent v1/v2 state.

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
GET /api/v2/runtime/motor-state
```

The v1 endpoint returns the unchanged v1 compatibility contract. The v2 endpoint returns Motor State v2 with observed embodiment evidence when the active BodyPrint contains supported observed values.

Before those prerequisites exist both endpoints return conflict rather than synthesizing identity/style values without a BodyPrint.

Machine-readable contracts:

- `contracts/bodyrig-motor-state-v1.schema.json`
- `contracts/bodyrig-motor-state-v2.schema.json`
