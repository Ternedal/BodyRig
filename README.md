# BodyRig

BodyRig giver ModelRig en visuel og kropslig tilstedeværelse.

- **ModelRig** tænker og producerer semantisk intent.
- **VoiceRig** lytter og taler.
- **BodyRig** bygger en portabel kropsprofil fra video og omsætter intent + taletiming til ansigt/kropsadfærd.
- **Kaliv / VR-klienter** renderer avataren.

## V1-mål

Det normale flow skal være:

> vælg 1–10 videoklip → identificér personen → udled bodyprint → byg/fit avatar → eksportér `.mrbody` → brug samme profil i Windows/Android/Quest-klienter.

V1 er local-first. Kildevideo er build-input og må ikke ende i den portable profil eller support-output.

## Kør bootstrap

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[test]"
pytest -q
bodyrig
```

BodyRig kører som standard på `127.0.0.1:8775`.

## Fra video til `.mrbody`

Den fysiske recovery-vej bruger først den pinned 4D-Humans/HMR2 + PHALP-adapter:

```powershell
bodyrig-recovery-preflight `
  --python "C:\path\to\4dh-python.exe" `
  --repo "C:\path\to\4D-Humans" `
  --out ".\bodyrig-recovery-preflight.json"

bodyrig-recover `
  --python "C:\path\to\4dh-python.exe" `
  --repo "C:\path\to\4D-Humans" `
  --out ".\bodyrig-recovery-proof.json" `
  "C:\video\person.mp4"
```

Når recovery-proofet er gyldigt, bygges den portable avatarprofil med:

```powershell
bodyrig-fit-avatar `
  .\bodyrig-recovery-proof.json `
  --body-id "min-avatar" `
  --name "Min avatar" `
  --out ".\min-avatar.mrbody"
```

Den første fitter (`procedural-vrm1`) er bevidst en neutral placeholder for visuel identitet, men dens kropsproportioner drives af source-derived BodyPrint-data. Den producerer en reel VRM 1.0-humanoid og gør det eksplicit i metadata, at avataren er en placeholder. En almindelig GLB-fil omdøbt til `.vrm` bliver afvist.

## Arkitektur

```text
ModelRig -- BodyCue ------------------+
                                      v
                                  BodyRig ----> renderer/Kaliv/VR
                                      ^
VoiceRig -- utterance/viseme timing --+

video --> recovery-engine (isolated) --> canonical 3D joints/tracks
      --> BodyRig bodyprint extractor --> avatar fitting/VRM --> .mrbody
```

Recovery-motorer og avatar-fitters holdes bag udskiftelige grænser, så research-stack, checkpoints og kropsmodel-licenser ikke bliver skjulte runtime-afhængigheder.

Se `docs/ARCHITECTURE.md`, `docs/MRBODY_SPEC.md` og `docs/AVATAR_FITTING.md`.
