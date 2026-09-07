# Automatic production activation

Denne vej erstatter human visual attestation som production-gate. Eksisterende human review-scripts beholdes kun som debug/inspektion og er ikke authority for automatisk activation.

Forudsætning: den eksisterende source-derived physical clone + Gate A har produceret et fresh acceptance directory med `bodyrig-acceptance.json`, runtime payloads og low-risk skin QA.

Kør derefter én kommando på Windows-riggen med Quest tilsluttet via den pinned Unity ADB:

```powershell
pwsh .\run-automatic-production-activation.ps1 -AcceptanceDir "C:\path\to\acceptance"
```

Top-wrapperen udfører i rækkefølge:

1. WindowsPlayer renderer/deformation probe;
2. deterministic skinned-mesh machine-quality grading;
3. Quest-class renderer/deformation probe på de samme hashbundne runtime bytes;
4. samme machine-quality grading på Quest;
5. fail-closed `bodyrig.automatic_release_gate` på hele evidence-kæden;
6. create-only `bodyrig-release-acceptance.json` v2 med `production_activation=true`.

Automatic quality måler den komplette `humanoid-muscle-sweep-v1` med `SkinnedMeshRenderer.BakeMesh`: non-finite vertices, faktisk ændret vertex-andel, RMS/max deformation relativt til avatarhøjde og neutral restoration. Final gate genberegner threshold-beslutningen fra receiptets rå metrics og kræver desuden Gate A skin QA `automated_assessment=low-risk`.

Ingen checkbox, fritekst-note eller menneskelig attestation kan få automatic gate til at passere.

Output ved succes:

```text
BODYRIG AUTOMATIC PRODUCTION ACTIVATION: PASS
production_activation=true
```

`production_activation=true` betyder kun, at den hashbundne BodyRig body/platform-kæde er automatisk accepteret. ModelRig/Kaliv activation har sin egen downstream gate og skal konsumere dette exact release-receipt.
