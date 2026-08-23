# BodyRig

BodyRig giver ModelRig en visuel og kropslig tilstedeværelse.

- **ModelRig** tænker og producerer semantisk intent.
- **VoiceRig** lytter og taler.
- **BodyRig** bygger en portabel kropsprofil fra video og omsætter intent + taletiming til ansigt/kropsadfærd.
- **Kaliv / VR-klienter** renderer avataren.

## V1-mål

Det normale flow skal være:

> vælg 1–10 videoklip → identificér personen → udled bodyprint → byg/fit avatar → eksportér `.mrbody` → materialisér validerede runtime-assets → brug samme profil i Windows/Android/Quest-klienter.

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

## Klargør recovery-miljøet på Windows

BodyRig kan oprette et separat, pinned recovery-miljø uden at blande 4D-Humans/PHALP ind i BodyRigs egen runtime:

```powershell
.\setup-recovery-windows.ps1 `
  -SmplModelPath "C:\Downloads\basicModel_neutral_lbs_10_207_0_v1.0.0.pkl"
```

Scriptet:

- opretter en managed recovery-root under `%LOCALAPPDATA%\BodyRig\recovery`;
- checker 4D-Humans ud på den eksakte BodyRig-pin;
- checker PHALP ud på den eksakte BodyRig-pin;
- opretter et separat Conda-miljø fra den pinned 4D-Humans `environment.yml`;
- installerer begge lokale checkouts editable, så versionerne ikke driver;
- kopierer kun SMPL-modellen, hvis brugeren selv leverer den;
- kører BodyRigs recovery-preflight til sidst.

SMPL-modellen downloades eller redistribueres **ikke** af BodyRig. Hvis den ikke er leveret, afslutter setup med en eksplicit blokeret status og fortæller den forventede filplacering.

Upstream 4D-Humans anbefaler Python 3.10/Conda og har native dependencies, som kan være den første praktiske Windows-risiko. Derfor er setup fail-closed: installation/preflight skal faktisk bestå på målriggen; BodyRig antager ikke, at et upstream Linux-orienteret research-stack automatisk virker på Windows.

## Fra video til `.mrbody`

Den fysiske recovery-vej bruger den pinned 4D-Humans/HMR2 + PHALP-adapter:

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

## `.mrbody` → renderer-runtime

Renderere skal ikke selv udpakke pakken eller vælge en løs VRM. BodyRig materialiserer kun de payloads, der allerede har bestået `.mrbody`-valideringen:

```powershell
bodyrig-materialize `
  ".\min-avatar.mrbody" `
  --out ".\runtime"
```

Det giver bl.a. `runtime/runtime-manifest.json`, `runtime/avatar.vrm` og `runtime/bodyprint.json`. Manifestet indeholder den eksakte package-SHA256. `validate-rig.ps1` udfører dette trin automatisk.

## Fysisk end-to-end acceptance

På målriggen kan hele den automatiske recovery/fitting/materialiseringskæde bindes sammen med ét kald:

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
- valid VRM 1.0;
- runtime-assets materialiseret fra den validerede package og bundet via runtime-manifest-SHA.

Acceptance-outputtet er write-once: en ikke-tom outputmappe genbruges ikke. Kilde-filnavne skrives ikke i acceptance-rapporten. SMPL-filen redistribueres ikke af BodyRig; den skal være lovligt anskaffet separat.

Et automatiseret PASS **er ikke** det samme som release acceptance: rapporten efterlader `physical_renderer_acceptance=pending` og `production_activation=false`.

### Bind fysisk renderer-bevis til samme runtime-bytes

Reference-rendereren åbner Gate A's `runtime/runtime-manifest.json` via `LoadRuntimeAsync(...)`; den har ingen offentlig loose-VRM acceptance-vej.

Efter fysisk load-test oprettes én immutable attestationsfil pr. platform:

```powershell
.\record-renderer-acceptance.ps1 `
  -AcceptanceReport "C:\acceptance\bodyrig-acceptance.json" `
  -RuntimeManifest "C:\acceptance\runtime\runtime-manifest.json" `
  -Platform "windows-unity-univrm" `
  -Pass `
  -RendererName "BodyRig Unity/UniVRM reference renderer" `
  -RendererVersion "Unity 2022.3 LTS / UniVRM <exact version>" `
  -QualityNote "Humanoid load, proportions and reference Motor State verified"

.\record-renderer-acceptance.ps1 `
  -AcceptanceReport "C:\acceptance\bodyrig-acceptance.json" `
  -RuntimeManifest "C:\acceptance\runtime\runtime-manifest.json" `
  -Platform "android-quest-class" `
  -Pass `
  -RendererName "BodyRig Unity/UniVRM Quest renderer" `
  -RendererVersion "Unity 2022.3 LTS / UniVRM <exact version> / Quest build <id>" `
  -QualityNote "Same accepted runtime and Motor State verified on Quest-class runtime"
```

Hver renderer-attestation bliver bundet til Gate A-reportens SHA-256, `.mrbody`-SHA-256, runtime-manifest-SHA-256, `avatar.vrm`-SHA-256, `bodyprint.json`-SHA-256, BodyRig Git-revision og body-id. Scriptet læser selv `.mrbody/checksums.json` og afviser materialiserede payloads, hvis deres bytes ikke matcher pakken. En renderer-attestation kan ikke selv aktivere production.

### Final release gate

Først når begge platformfiler findes, kan release-evidensen afsluttes:

```powershell
.\complete-acceptance.ps1 `
  -AcceptanceReport "C:\acceptance\bodyrig-acceptance.json" `
  -WindowsRendererReport "C:\acceptance\bodyrig-renderer-acceptance-windows.json" `
  -QuestRendererReport "C:\acceptance\bodyrig-renderer-acceptance-quest.json"
```

Final-gaten genverificerer hele Gate A, package-checksums, runtime-manifest-hash, Git-head og begge renderer-reporters bindinger. Kun den resulterende `bodyrig-release-acceptance.json` må have `production_activation=true`.

CI workflow run #66 på head `15d6974246d01ac15ca8b42b6f3db34b4ad466c2` beviste den komplette ikke-fysiske gate: Python 3.11/3.12, schema-validering, PowerShell-parser og den eksekverede package → runtime → Windows/Quest evidence → release-kæde inklusive negative tamper-cases.

Det erstatter **ikke** den fysiske gate: issue #2 kræver stadig rigtig video på målriggen, og issue #3 kræver stadig fysisk Unity/UniVRM-load på Windows og Quest/Android-class hardware.

Se `docs/RIG_ACCEPTANCE.md` for den fulde evidens- og fail-closed-model.

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
      --> validated runtime materialization --> renderer
```

Recovery-motorer og avatar-fitters holdes bag udskiftelige grænser, så research-stack, checkpoints og kropsmodel-licenser ikke bliver skjulte runtime-afhængigheder.

Se `docs/ARCHITECTURE.md`, `docs/MRBODY_SPEC.md`, `docs/AVATAR_FITTING.md`, `docs/MOTOR_STATE.md` og `docs/RIG_ACCEPTANCE.md`.
