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

## Fysisk end-to-end acceptance

På målriggen kan hele den automatiske kæde bindes sammen med ét kald:

```powershell
.\validate-rig.ps1 `
  -Source "C:\video\person-1.mp4","C:\video\person-2.mp4" `
  -ExternalPython "C:\path\to\4dh-python.exe" `
  -FourDHumansRepo "C:\path\to\4D-Humans" `
  -BodyId "min-avatar" `
  -Name "Min avatar"
```

Validatoren kræver som standard:

- clean BodyRig checkout og registrerer den eksakte Git-revision;
- pinned 4D-Humans/PHALP-kode;
- den nødvendige neutral SMPL-model i den eksterne recovery-installation;
- CUDA i recovery-Python;
- rigtig recovery med mindst to observerede frames;
- source-derived shape + motion i BodyPrint;
- recovery-proof og `.mrbody` med identisk BodyPrint;
- korrekt recovery/avatar-fitting provenance;
- valid VRM 1.0.

Kilde-filnavne skrives ikke i acceptance-rapporten. SMPL-filen redistribueres ikke af BodyRig; den skal være lovligt anskaffet separat.

Et automatiseret PASS **er ikke** det samme som release acceptance: rapporten efterlader `physical_renderer_acceptance=pending` og `production_activation=false`, indtil den genererede avatar også er load-testet i Unity/UniVRM på Windows og Android/Quest-class runtime.

## Bevægelsesstil

ModelRig sender fortsat semantiske `BodyCue`-events. BodyRig resolver dem gennem det aktive BodyPrint til `BodyRig Motor State v1`, så den samme gestus kan have forskellig amplitude, hovedbevægelse, gaze og tale-ekspressivitet for forskellige profiler.

Renderer-klienterne skal konsumere Motor State og må ikke selv genfortolke ModelRig-cuet som en ny personlighed/motion-profile.

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

Se `docs/ARCHITECTURE.md`, `docs/MRBODY_SPEC.md`, `docs/AVATAR_FITTING.md` og `docs/MOTOR_STATE.md`.
