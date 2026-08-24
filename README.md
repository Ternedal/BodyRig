# BodyRig

BodyRig giver ModelRig en visuel og kropslig tilstedeværelse.

- **ModelRig** tænker og producerer semantisk intent.
- **VoiceRig** lytter og taler.
- **BodyRig** bygger en portabel kropsprofil fra video og omsætter intent + taletiming til ansigt/kropsadfærd.
- **Kaliv / VR-klienter** renderer avataren.

## V1-mål

Det normale flow er:

> vælg 1–10 videoklip → identificér personen → udled BodyPrint → rekonstruér visuel identitet/krop → fit source-derived VRM 1.0 → eksportér `.mrbody` → materialisér validerede runtime-assets → brug de samme bytes i Windows/Android/Quest-klienter.

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
- runtime materialiseret fra den **samme** accepterede `.mrbody`.

Gate A-bundlen indeholder den accepterede `.mrbody`, runtime-manifest/payloads samt kopier af physical-clone session- og readiness-evidence. Den efterlader stadig `physical_renderer_acceptance=pending` og `production_activation=false`.

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

Efter fysisk WindowsPlayer-load og visuel kontrol:

```powershell
.\record-renderer-acceptance.ps1 `
  -AcceptanceReport "C:\acceptance\bodyrig-acceptance.json" `
  -RuntimeManifest "C:\acceptance\runtime\runtime-manifest.json" `
  -ProbeReport "C:\acceptance\windows-probe.json" `
  -Platform "windows-unity-univrm" `
  -Pass `
  -RendererName "BodyRig Unity/UniVRM reference renderer" `
  -RendererVersion "Unity 2022.3 LTS / UniVRM <exact version>" `
  -QualityNote "Source-derived identity, proportions, deformation and motion verified"
```

Efter samme runtime er loadet på Quest-class Android-hardware:

```powershell
.\record-renderer-acceptance.ps1 `
  -AcceptanceReport "C:\acceptance\bodyrig-acceptance.json" `
  -RuntimeManifest "C:\acceptance\runtime\runtime-manifest.json" `
  -ProbeReport "C:\acceptance\quest-probe.json" `
  -Platform "android-quest-class" `
  -Pass `
  -RendererName "BodyRig Unity/UniVRM Quest renderer" `
  -RendererVersion "Unity 2022.3 LTS / UniVRM <exact version> / Quest build <id>" `
  -QualityNote "Same accepted high-fidelity runtime verified on Quest-class hardware"
```

Renderer-attesteringen genverificerer high-fidelity clone-lineage, package provenance, session/readiness-hashes, exact clean BodyRig-revision, package/runtime/payload-byte-identitet og machine-proben. Hver platformrapport forbliver non-activating med `production_activation=false`.

Den første rigtige high-fidelity clone skal især inspiceres for cross-limb skin-weight leakage ved arm/torso, ben og hænder. Nearest-vertex skin transfer opgraderes først, hvis fysisk evidens viser, at det er nødvendigt.

## Final release gate

Først når begge platformers machine probes og operatorattesteringer findes, kan release-evidensen afsluttes:

```powershell
.\complete-acceptance.ps1 `
  -AcceptanceReport "C:\acceptance\bodyrig-acceptance.json" `
  -WindowsRendererReport "C:\acceptance\bodyrig-renderer-acceptance-windows.json" `
  -WindowsProbeReport "C:\acceptance\windows-probe.json" `
  -QuestRendererReport "C:\acceptance\bodyrig-renderer-acceptance-quest.json" `
  -QuestProbeReport "C:\acceptance\quest-probe.json"
```

Final-gaten genverificerer high-fidelity Stash/SiTH-lineage, `placeholder_avatar=false`, package provenance, clone-session/readiness-evidence, package-checksums, runtime-manifest, Git-head, begge machine probes og begge renderer-reporters hashbindinger.

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
            --> .mrbody --> validated runtime materialization
            --> WindowsPlayer + Quest byte-bound acceptance
```

Research-stacks, checkpoints og kropsmodel-licenser holdes bag build-time grænser, så de ikke bliver skjulte runtime-afhængigheder i `.mrbody`.

Se `docs/ARCHITECTURE.md`, `docs/MRBODY_SPEC.md`, `docs/AVATAR_FITTING.md`, `docs/MOTOR_STATE.md`, `docs/PHYSICAL_CLONE_SESSION.md` og `docs/RIG_ACCEPTANCE.md` for de detaljerede kontrakter og gates.
