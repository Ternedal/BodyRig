# BodyRig

BodyRig giver ModelRig en visuel og kropslig tilstedeværelse.

- **ModelRig** tænker og producerer semantisk intent.
- **VoiceRig** lytter og taler.
- **BodyRig** bygger en portabel kropsprofil fra video og omsætter intent + taletiming til ansigt/kropsadfærd.
- **Kaliv / VR-klienter** renderer avataren.

## V1-mål

Det normale flow er:

> vælg 1–10 videoklip → identificér personen → udled BodyPrint → rekonstruér visuel identitet/krop → fit source-derived VRM 1.0 → eksportér `.mrbody` → anatomisk skin-QA → materialisér validerede runtime-assets → kør samme faste deformation-sweep på Windows/Quest → brug de samme bytes i klienterne.

V1 er local-first. Kildevideo er build-input og må ikke ende i den portable profil eller support-output.

## Bootstrap

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[test]"
pytest -q
bodyrig
```

BodyRig kører som standard på `127.0.0.1:8775`.

## Klargør målriggen

Recovery-, PHALP-, SiTH-, OpenPose- og modelafhængigheder holdes uden for BodyRigs portable runtime. Den samlede Windows-klargøring er:

```powershell
.\setup-rig-windows.ps1 `
  -SmplModelPath "C:\Downloads\basicModel_neutral_lbs_10_207_0_v1.0.0.pkl"
```

Setup er fail-closed og producerer et lokalt `bodyrig-rig-setup`-bevis. BodyRig downloader eller redistribuerer ikke licensbelagte SMPL/SMPL-X-assets på brugerens vegne; nødvendige assets skal være lovligt anskaffet separat.

Recovery alene kan stadig diagnosticeres direkte. Den pinned PHALP-checkout er obligatorisk i preflighten:

```powershell
bodyrig-recovery-preflight `
  --python "C:\path\to\4dh-python.exe" `
  --repo "C:\path\to\4D-Humans" `
  --phalp-repo "C:\path\to\PHALP" `
  --out ".\bodyrig-recovery-preflight.json"
```

Den ældre `run-physical-gate.ps1` / `validate-rig.ps1`-vej er fortsat nyttig til recovery- og procedural-VRM-diagnostik, men en procedural placeholder er **ikke** længere produktions-Gate A og kan ikke ende i `production_activation=true`.

## Canonical fysisk high-fidelity clone

Når målriggen er klar, køres den rigtige Stash → recovery → visual identity → SiTH/SMPL-X → VRM-kæde med:

```powershell
.\clone-body-from-stash-ready.ps1 `
  -PerformerId 123 `
  -BodyId "performer-123"
```

Launcheren binder kørselen til den eksakte BodyRig Git-revision, kræver clean checkout som standard, kører en frisk live-readiness, binder readiness-SHA-256 til sessionen og nægter PASS, hvis Git HEAD ændrer sig under den lange clone.

Standard-output skrives uden for repoet under `%LOCALAPPDATA%\BodyRig\physical-clones`; session/readiness-evidence skrives under `%LOCALAPPDATA%\BodyRig\physical-clone-sessions`. Det forhindrer genererede clone-artifacts i selv at gøre checkout dirty.

En PASS-session er endnu ikke produktionsacceptance. Den skal promoveres uden at bygge avataren igen:

```powershell
.\accept-physical-clone.ps1 `
  -SessionReport "C:\Users\you\AppData\Local\BodyRig\physical-clone-sessions\performer-123-....json"
```

Denne Gate A-bro kræver bl.a.:

- samme eksakte, clean BodyRig-revision som clone-sessionen;
- uændret readiness/session-evidence;
- recovery-proof og package med identisk BodyPrint/source count/recovery provenance;
- visual-identity provenance bundet til identity-profile;
- built-in `sith-smplx-vrm` revision `1`;
- VRM 1.0 og `placeholder_avatar=false`;
- source-derived shape/motion;
- strukturelt gyldige skin weights;
- en create-only anatomisk skin-QA bundet til package- og avatar-SHA;
- runtime materialiseret fra den **samme** accepterede `.mrbody`.

Gate A binder også Python-koden til samme checkout. Den valgte `BodyRigPython` — som default repoets `.venv\Scripts\python.exe`, ellers en eksplicit/fundet interpreter — skal kunne importere `bodyrig`, og `bodyrig.__file__` skal resolve til netop `<checkout>\bodyrig\__init__.py`. En global wheel eller et andet checkout afvises derfor, selv hvis selve PowerShell-scriptet ligger på den korrekte Git-revision.

Gate A-bundlen indeholder den accepterede `.mrbody`, `bodyrig-skin-qa.json`, runtime-manifest/payloads samt kopier af physical-clone session- og readiness-evidence. Skin-QA klassificerer cross-region weight leakage som `low-risk`, `review` eller `high-risk`, men markerer altid `manual_review_required=true`; den erstatter altså ikke den fysiske deformationstest. Gate A efterlader fortsat `physical_renderer_acceptance=pending` og `production_activation=false`.

Se `docs/SKIN_QA.md` for metode, thresholds og trust boundary.

## Genoptag fysisk acceptance sikkert

Fysisk acceptance kan strække sig over flere sessioner og maskiner. Brug den read-only status checker i stedet for at gætte, hvilket trin der mangler:

```powershell
.\physical-acceptance-status.ps1 `
  -SessionReport "C:\path\to\bodyrig-physical-clone-session.json"
```

Når Gate A allerede findes:

```powershell
.\physical-acceptance-status.ps1 `
  -AcceptanceDir "C:\acceptance"
```

CLI-varianten er:

```powershell
bodyrig-acceptance-status --acceptance-dir "C:\acceptance"
```

En normal wheel-installation kan altid bruges til **read-only inspection**, fordi wheel'en indeholder den samme byte-identiske `reference-renderer/renderer-contract.json`. Men site-packages er ikke et BodyRig Git-checkout og må derfor ikke bruges som authority for fysiske operator-kommandoer. Hvis status-CLI'en ikke kan auto-detektere et checkout med den komplette canonical operator dependency closure, viser den status men sætter `next_command=null` og markerer resultatet `Inspection-only`.

Hvis CLI'en køres fra en separat installation, kan et rigtigt checkout bindes eksplicit:

```powershell
bodyrig-acceptance-status `
  --acceptance-dir "C:\acceptance" `
  --operator-root "C:\Users\you\Desktop\BodyRig"
```

Før en executable next-command vises, verificerer statuslaget at operator-root er et Git-checkout med hele den nødvendige closure: reference-wrappers, de underliggende Windows/Quest/attestation/release-scripts, `renderer-contract.json`, renderer-build-scriptet samt Unity `ProjectVersion.txt` og `Packages/manifest.json`. Et sparse checkout er derfor kun acceptabelt, hvis alle disse filer faktisk er materialiseret. Derefter skal `git rev-parse HEAD` matche acceptance-revisionen, og `git status --porcelain` skal være clean. Forkert revision eller dirty checkout bliver `BLOCKED` med exit code `3`; manglende operator-dependencies eller malformed/tampered evidence er `ERROR` med exit code `2`. Når checkoutet er validt, vises next-command med en absolut script-path, så den ikke afhænger af current working directory.

Status-checkeren **muterer ingen evidence**. Den læser og re-hasher den eksisterende kæde og returnerer det præcise næste gate/kommando, når en gyldig operator-authority er tilgængelig:

`Gate A → Windows probe → Windows human attestation → Quest probe → Quest human attestation → final release`.

Hvis evidence er inkonsistent — fx et ufuldstændigt machine/deformation-par, både nyt og legacy layout, forkert embedded BodyRig build-revision eller en attestation der ikke længere hasher til sine eksakte probe-filer — returnerer den `ERROR` i stedet for at foreslå et næste trin. Complete legacy root-par kan stadig inspiceres for backward compatibility, men den canonical V1 release-policy kræver de nye contract-bound evidence-directories. `-Json` / `--json` kan bruges til maskinlæsbar status.

## `.mrbody` → renderer-runtime

Renderere må ikke selv udpakke pakken eller vælge en løs VRM. BodyRig materialiserer kun payloads, som allerede har bestået `.mrbody`-valideringen:

```powershell
bodyrig-materialize `
  ".\performer-123.mrbody" `
  --out ".\runtime"
```

`runtime/runtime-manifest.json` indeholder den eksakte package-SHA-256. I produktionsacceptance gør `accept-physical-clone.ps1` materialiseringen automatisk fra den accepterede high-fidelity package.

## Fysisk renderer-acceptance

Windows og Quest skal loade **samme Gate A runtime-manifest og samme package-bytes**. Renderer-proben skal komme fra den byggede runtime, ikke fra Unity Editor eller en generisk Android-telefon.

Renderer-builden kræver clean BodyRig checkout og embedder den eksakte Git-revision i player/APK som build provenance. Machine- og deformation-proberne læser revisionen fra de byggede bytes, og Gate B/C kræver den lig Gate A-revisionen.

Reference-rendererens identitet er maskin-authoritative i `reference-renderer/renderer-contract.json`. Kontrakten binder renderer-navn/version samt de pinned Unity/UniVRM-versioner. Operatøren skal derfor **ikke** skrive eller gætte renderer-versionen ved human attestation.

Hver platform-wrapper bruger en staging-directory og materialiserer først den canonical evidence-directory, når **begge** probe-filer er produceret og valideret. Et crash mellem machine- og deformation-proben efterlader derfor ikke et halvt canonical create-only evidence-par.

Reference-rendereren kører efter normal VRM/Humanoid-validering en fast `humanoid-muscle-sweep-v1` med seks poser i denne rækkefølge:

`neutral → arms_abduction → elbows_flexed → arms_forward → left_leg_lift → knee_flexion`.

Sweepet bruger Unity Humanoid-muscles via `HumanPoseHandler`, skriver create-only `bodyrig-deformation-probe` v1 og fortsætter derefter samme sekvens i loop, så operatøren kan inspicere skulder, albue, håndled, hofte, knæ og cross-limb deformation. Evidence beviser kun, at de faste poser faktisk blev anvendt på den konkrete build/runtime; **det graderer ikke visuelt resultatet**.

### WindowsPlayer

Canonical Windows-kørslen bruger samme contract-bound transaction-lag som Quest:

```powershell
.\run-reference-windows-renderer-probe.ps1 `
  -AcceptanceDir "C:\acceptance"
```

Efter begge valideringslag commit'es parret samlet som `windows-evidence/`. `run-windows-renderer-probe.ps1` er fortsat den interne/lavniveau player/build-implementation, men er ikke V1's canonical production entrypoint.

Efter fysisk visuel review:

```powershell
.\record-reference-renderer-acceptance.ps1 `
  -AcceptanceDir "C:\acceptance" `
  -Platform "windows-unity-univrm" `
  -QualityNote "Fixed deformation sweep reviewed: identity, proportions, shoulders, elbows, wrists, hips and knees acceptable"
```

### Quest-class Android

Canonical Quest-kørslen bruger et ekstra contract-bound transaction-lag omkring den lavniveau ADB-wrapper:

```powershell
.\run-reference-quest-renderer-probe.ps1 `
  -AcceptanceDir "C:\acceptance"
```

Efter ADB-pull og begge valideringslag commit'es parret samlet som `quest-evidence/`. `run-quest-renderer-probe.ps1` er fortsat den interne/lavniveau ADB-implementation, men er ikke V1's canonical production entrypoint.

Efter samme sweep er gennemgået i headsettet:

```powershell
.\record-reference-renderer-acceptance.ps1 `
  -AcceptanceDir "C:\acceptance" `
  -Platform "android-quest-class" `
  -QualityNote "Same fixed deformation sweep and accepted high-fidelity runtime reviewed on Quest-class hardware"
```

`record-reference-renderer-acceptance.ps1` afleder renderer-navn/version og exact Unity-version fra `renderer-contract.json`, kræver at machine/deformation evidence matcher kontrakten og kalder derefter den eksisterende hårde `record-renderer-acceptance.ps1`. Human `QualityNote` forbliver direkte hash-bundet til det konkrete deformation-run.

Den første rigtige high-fidelity clone skal især sammenholde skin-QA-resultatet med den faste fysiske sweep ved arm/torso, ben, hænder, skuldre, albuer og knæ. Nearest-vertex skin transfer opgraderes først, hvis fysisk evidens viser, at det er nødvendigt.

## Final release gate

Når begge platformers canonical machine/deformation-par og reference-attesteringer findes, afsluttes V1 gennem reference policy-wrapperen:

```powershell
.\complete-reference-acceptance.ps1 `
  -AcceptanceDir "C:\acceptance"
```

Wrapperen kræver canonical `windows-evidence/` og `quest-evidence/`, genverificerer renderer name/version, exact Unity `6000.3.13f1` samt `humanoid-muscle-sweep-v1` på begge platformes probe/deformation/attestation og kalder derefter den generiske `complete-acceptance.ps1`, som fortsat ejer den fulde byte-, hash-, provenance-, platform-, device- og revision-binding.

Kun den resulterende `bodyrig-release-acceptance.json` må have:

```json
{
  "release_gate_pass": true,
  "production_activation": true
}
```

## Bevægelsesstil

ModelRig sender semantiske `BodyCue`-events. BodyRig resolver dem gennem det aktive BodyPrint til `BodyRig Motor State v1`, så den samme gestus kan have forskellig amplitude, hovedbevægelse, gaze og tale-ekspressivitet for forskellige profiler.

Renderer-klienterne skal konsumere Motor State og må ikke selv genfortolke ModelRig-cuet som en ny personlighed/motion-profile.

## Arkitektur

```text
ModelRig -- BodyCue ------------------+
                                      v
                                  BodyRig ----> renderer/Kaliv/VR
                                      ^
VoiceRig -- utterance/viseme timing --+

Stash/video --> pinned recovery + PHALP --> canonical tracks/BodyPrint
            --> visual identity --> pinned SiTH/SMPL-X --> VRM 1.0
            --> .mrbody --> anatomical skin QA --> validated runtime materialization
            --> exact-revision renderer build --> deterministic Humanoid deformation sweep
            --> atomic Windows/Quest evidence pairs --> contract-bound human review
            --> reference release policy --> byte/build/revision-bound production acceptance
```

Research-stacks, checkpoints og kropsmodel-licenser holdes bag build-time grænser, så de ikke bliver skjulte runtime-afhængigheder i `.mrbody`.

Se `docs/ARCHITECTURE.md`, `docs/MRBODY_SPEC.md`, `docs/AVATAR_FITTING.md`, `docs/MOTOR_STATE.md`, `docs/PHYSICAL_CLONE_SESSION.md`, `docs/SKIN_QA.md` og `docs/RIG_ACCEPTANCE.md` for de detaljerede kontrakter og gates.