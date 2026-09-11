# BodyRig Motor State v1 + v2 + v3

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

## BodyCue v2 and Motor State v3

BodyCue v1 is frozen. It has no locomotion semantic and therefore cannot accidentally turn Movement Identity observations into an action.

BodyCue v2 adds one explicit `locomotion` object:

```json
{
  "type": "modelrig-body-cue",
  "version": 2,
  "utterance_id": "u-walk",
  "locomotion": {
    "action": "walk",
    "effort": 0.5
  }
}
```

Supported actions are `walk`, `turn_left`, `turn_right`, and `stop`. Omitting `effort` means natural effort (`0.5`), not a generic gait.

Motor State v3 is the first performed contract allowed to contain locomotion. It resolves the explicit action through complete source-derived Movement Identity:

- `walk` uses the subject's observed cadence, relative stride length, stance width, vertical bounce, arm swing, and transition style;
- `turn_left` / `turn_right` use the requested direction plus the subject's observed turn-speed magnitude and transition style;
- `stop` carries the explicit stop semantic and the subject's observed transition style;
- effort may vary pace/amplitude within bounded limits around the observed identity; it never replaces the identity with generic defaults.

Example natural walk output:

```json
{
  "type": "bodyrig-motor-state",
  "version": 3,
  "body_id": "person-a",
  "utterance_id": "u-walk",
  "motion": {
    "energy": 0.72,
    "head_motion": 0.88
  },
  "locomotion": {
    "action": "walk",
    "effort": 0.5,
    "transition_intensity": 0.31,
    "cadence_spm": 116.0,
    "stride_length_to_height": 0.34,
    "stance_width_to_height": 0.13,
    "vertical_bounce_to_height": 0.024,
    "arm_swing_to_height": 0.19
  },
  "embodiment": {
    "source": "modelrig-bodyprint-v1",
    "observed": {
      "walk_cadence_spm": 116.0,
      "stride_length_to_height": 0.34
    }
  }
}
```

This is fail-closed. An explicit locomotion cue requires complete Movement Identity. Missing gait/posture/dynamics/idle evidence is an error; BodyRig does not substitute a generic walk. Explicit turns additionally require non-zero observed turn-speed evidence.

A BodyCue v2 must never be requested through Motor State v1 or v2 because doing so would silently drop its locomotion semantic. The runtime rejects that downgrade and requires Motor State v3.

Movement Identity observations alone still cannot produce a `locomotion` section. A BodyCue v1 routed through v3 remains non-locomoting unless an explicit v2 locomotion cue exists.

### v3 exposure boundary

The Python runtime exposes `BodyRuntime.motor_state_v3()` for contract/resolver testing. The HTTP runtime endpoint is intentionally not exposed until the reference renderer can consume and realize Motor State v3. This prevents an API client from receiving an apparently actionable locomotion contract before the production reference consumer exists.

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

After a body is active and a BodyCue v1 has been received:

```text
GET /api/v1/runtime/motor-state
GET /api/v2/runtime/motor-state
```

The v1 endpoint returns the unchanged v1 compatibility contract. The v2 endpoint returns Motor State v2 with observed embodiment evidence when the active BodyPrint contains supported observed values.

Before those prerequisites exist both endpoints return conflict rather than synthesizing identity/style values without a BodyPrint. BodyCue v2 / Motor State v3 HTTP exposure remains blocked until renderer realization lands.

Machine-readable contracts:

- `contracts/body-cue-v1.schema.json`
- `contracts/body-cue-v2.schema.json`
- `contracts/bodyrig-motor-state-v1.schema.json`
- `contracts/bodyrig-motor-state-v2.schema.json`
- `contracts/bodyrig-motor-state-v3.schema.json`
