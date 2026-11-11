# BodyRig in the Kaliv system

How BodyRig connects to the other Kaliv repositories, as implemented on `main`.
Every connection below names the file that implements it. If this page and that
file disagree, the file is right.

This page describes interfaces. It does not define authority, and it is not
evidence that anything is activated, released or physically accepted.

- Who owns what across the whole system: ModelRig,
  [`docs/KALIV_SYSTEM_DEFINITION.md`](https://github.com/Ternedal/ModelRig/blob/main/docs/KALIV_SYSTEM_DEFINITION.md).
- The body-domain boundary between ModelRig and BodyRig: ModelRig,
  [`docs/BODYRIG_AUTHORITY.md`](https://github.com/Ternedal/ModelRig/blob/main/docs/BODYRIG_AUTHORITY.md).
- All Kaliv repositories and their roles:
  [Kaliv README](https://github.com/Ternedal/Kaliv#relaterede-repositories).
- BodyRig's own architecture: [`ARCHITECTURE.md`](ARCHITECTURE.md).

## What BodyRig owns

BodyRig is the author of body identity: the `.mrbody` package, BodyPrint,
source-derived Movement Identity and Motor State. The machine-readable contracts
are the JSON schemas in `contracts/`; [`MRBODY_SPEC.md`](MRBODY_SPEC.md) and
[`MOTOR_STATE.md`](MOTOR_STATE.md) describe them.

## ModelRig

| Direction | Connection | Implemented in |
|---|---|---|
| BodyRig → ModelRig (file) | A `.mrbody` v1 package. ModelRig installs it in its own profile store (`KALIV_BODY_STORE`) and serves it to clients. | BodyRig `bodyrig/package.py`; ModelRig `worker/app/body_assets.py` |
| BodyRig → ModelRig (schemas) | ModelRig carries copies of the `.mrbody`, BodyPrint, provenance, checksum and BodyCue schemas in its `contracts/bodyrig/` directory. They are compatibility snapshots; BodyRig is the author. | BodyRig `contracts/`; ModelRig `tests/workflow_mrbody_cross_repo_contract.py` |
| BodyRig → ModelRig (HTTP) | Person Studio calls ModelRig for personality auditions: `GET /healthz`, `GET /api/v1/models`, `POST /api/v1/chat`. | `bodyrig/modelrig_client.py` |
| ModelRig → BodyRig (HTTP) | None today. See below. | — |

**Person Studio's ModelRig client.** `MODELRIG_URL` (default
`http://127.0.0.1:8080`) and `MODELRIG_TOKEN`, which is sent as a bearer token;
ModelRig requires one on loopback too. The client accepts loopback hosts only
and does not follow redirects.

**Body ids.** ModelRig accepts only canonical `bodyid-<24 hex>` packages. The
`asset-*` packages from the experimental VRM export
([`vrm-export.md`](vrm-export.md)) pass ModelRig's package validation but cannot
be loaded in Kaliv.

**Runtime.** BodyRig's runtime API is the contract for executing a semantic
BodyCue as a Motor State:

```text
POST /api/v1/runtime/cue
POST /api/v2/runtime/cue
GET  /api/v1/runtime/motor-state
GET  /api/v2/runtime/motor-state
POST /api/v1/runtime/speech-timing
GET  /api/v1/runtime/state
```

ModelRig does not call these routes. It runs its own in-process copy of the body
runtime (the `bodyrig/` package in the ModelRig repository) and serves the active
body and its render frames to clients itself, under `/api/v1/body/`. In BodyRig
the routes are used by Person Studio's own consoles
([`PERSON_UI.md`](PERSON_UI.md)).

## VoiceRig

| Direction | Connection | Implemented in |
|---|---|---|
| BodyRig → VoiceRig (HTTP) | Person Studio lists and previews voices, fetches `.mrvoice` packages, synthesizes audition audio and starts and follows voice build jobs. | `bodyrig/voicerig_client.py` |
| VoiceRig → BodyRig (HTTP) | None today. `POST /api/v1/runtime/speech-timing` is the contract for utterance timing; VoiceRig has no client for it. | `bodyrig/app.py` |

The client uses `VOICERIG_URL` (default `http://127.0.0.1:8765`), accepts
loopback hosts only, and calls `/api/health`, `/api/voices`,
`/api/voices/{package}/preview`, `/api/packages/{package}`,
`/api/tts/synthesize` and the job routes under `/api/jobs`.

## Kaliv clients

Kaliv on Android and Kaliv VR load the active body from ModelRig's backend
routes, not from BodyRig. The Unity project in `reference-renderer/` is BodyRig's
own acceptance renderer for Windows and Quest; it is not a Kaliv client.

## Repositories with no connection to BodyRig

VisionRig, LanguageRig, KalivNexus, KalivHub, KalivHub-Receiver and
SkyPlayer-Engine: BodyRig neither calls them nor is called by them.

The scene inspector ([`scene-inspector.md`](scene-inspector.md)) can produce
conditioning images intended for ModelRig's image and video generation
(Ternedal/ModelRig#2296). That hand-off is not implemented in BodyRig.

## Local services

| Service | Default address | Set by |
|---|---|---|
| BodyRig (Person Studio and API) | `127.0.0.1:8775` | `BODYRIG_HOST`, `BODYRIG_PORT` |
| ModelRig backend | `127.0.0.1:8080` | `MODELRIG_URL` (as seen from BodyRig) |
| VoiceRig sidecar | `127.0.0.1:8765` | `VOICERIG_URL` (as seen from BodyRig) |

BodyRig refuses a non-loopback bind and non-loopback requests unless
`BODYRIG_ALLOW_REMOTE=1`.
