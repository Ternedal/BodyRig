# BodyRig anatomical skin QA

BodyRig bruger i V1 en source-derived SiTH/SMPL-X reconstruction, hvor skin weights overføres fra den nærmeste SMPL-X-vertex i posed space. Den metode er enkel og reproducerbar, men ren geometrisk afstand kan ikke i sig selv bevise anatomisk korrekt skinning ved kontaktflader som arm/torso, hånd/krop eller ben/ben.

`bodyrig.skin_qa` er derfor en automatisk, read-only analyse af den allerede genererede high-fidelity `.mrbody`. Den ændrer aldrig avatarens mesh, skeleton eller weights.

## Kørsel

`accept-physical-clone.ps1` kører analysen automatisk før Gate A materialiserer renderer-runtime:

```powershell
.\accept-physical-clone.ps1 `
  -SessionReport "C:\path\to\bodyrig-physical-clone-session.json"
```

Den kan også køres separat til diagnostik:

```powershell
python -m bodyrig.skin_qa `
  "C:\path\to\performer-123.mrbody" `
  --out "C:\path\to\bodyrig-skin-qa.json"
```

Output er create-only `bodyrig-skin-qa` v1 og valideres mod `contracts/skin-qa-v1.schema.json`.

## Hvad analysen kontrollerer

Før risikovurderingen accepteres, verificerer analysen strukturelt:

- `.mrbody` validerer normalt;
- `avatar.vrm` er VRM 1.0;
- avataren er source-derived high fidelity og ikke placeholder;
- fitter er præcis `sith-smplx-vrm` revision `1`;
- rig-transfer er `nearest-smplx-vertex-lbs-inverse`;
- mesh indeholder `POSITION`, `JOINTS_0` og `WEIGHTS_0`;
- skin-joint indices er gyldige;
- skin weights er finite, non-negative og summerer til 1 inden for tolerance;
- ingen vertex har et tomt influence-set.

Derefter rekonstrueres skeletonets rest-pose fra glTF node-hierarkiet. Joints grupperes i fem anatomiske regioner:

- torso;
- venstre arm;
- højre arm;
- venstre ben;
- højre ben.

For hver stærkt klassificerbar limb-vertex måles den samlede weight-masse, der er overført til fysisk adskilte regioner. Eksempel: en tydelig venstre-arm-vertex må gerne blende mod torso omkring skulderen, men vægt på højre arm eller ben tæller som cross-region leakage.

Torso/limb blending klassificeres bevidst ikke som leakage, fordi det er nødvendigt omkring skuldre og hofter.

## Assessment

Rapporten giver én af tre automatiske vurderinger:

- `low-risk`: ingen væsentlig cross-region weight leakage fundet af heuristikken;
- `review`: målingerne ligger i et område, der fortjener ekstra fysisk opmærksomhed;
- `high-risk`: væsentlig anatomisk mistænkelig weight-masse er fundet.

V1-thresholds er evidence-policy og står eksplicit i rapporten. De kan derfor ikke ændres skjult efter en fysisk clone.

## Vigtigt: det er ikke en visuel dommer

Alle rapporter indeholder:

```json
{
  "structural_pass": true,
  "manual_review_required": true
}
```

Det er bevidst. Selv `low-risk` betyder ikke, at deformationen visuelt er god. Analysen kan eksempelvis ikke alene afgøre:

- om skulderen kollapser ved stor armrotation;
- om albue/knæ folder naturligt;
- om håndled og fingre deformerer pænt;
- om tøj/hår skærer gennem kroppen;
- om en geometrisk korrekt weight-fordeling stadig ser kunstig ud i bevægelse.

Omvendt blokerer `high-risk` ikke automatisk production, hvis den fysiske Windows/Quest-inspektion dokumenterer, at den konkrete avatar faktisk deformerer acceptabelt. Det forhindrer heuristikken i at blive en falsk ground truth.

## Evidence chain

High-fidelity Gate A gemmer `bodyrig-skin-qa.json` ved siden af:

```text
bodyrig-acceptance.json
bodyrig-physical-clone-session.json
bodyrig-rig-readiness.json
<BodyId>.mrbody
runtime/
```

Gate A binder rapportens SHA-256 og assessment ind i `bodyrig-acceptance.json`.

`record-renderer-acceptance.ps1` re-hasher rapporten og kræver, at:

- package SHA matcher den accepterede `.mrbody`;
- avatar SHA matcher den materialiserede `avatar.vrm`;
- body id matcher;
- assessment/state stadig er identisk med Gate A.

`complete-acceptance.ps1` gør samme validering igen og kopierer skin-QA-hash + assessment ind i final `bodyrig-release-acceptance` evidence.

En ændret eller manglende skin-QA-rapport efter Gate A får derfor renderer/release acceptance til at fejle.

## Hvordan første fysiske clone skal bruges

Første rigtige Stash/SiTH-clone skal sammenholde:

1. `nearest_distance_p95/max` fra fitteren;
2. `cross_region`-målingerne fra skin QA;
3. fysisk deformation i bygget WindowsPlayer;
4. samme deformation på Quest-class runtime.

Hvis de fysiske resultater viser reel cross-limb leakage, er næste tekniske ændring at evaluere nearest-surface/barycentric eller region-aware weight transfer. V1 skifter ikke transfermetode alene på baggrund af teoretisk mistanke.
