# BodyRig Personality Blueprint v1

BodyRig har allerede én samlet Person-model, hvor **krop**, **stemme** og **personlighed** versionsstyres hver for sig og først aktiveres efter en faktisk ModelRig + VoiceRig audition. Personality Blueprint ændrer ikke den model. Det er et authoring- og grounding-lag foran den eksisterende `personality-rXXXX` kandidat.

## Hvorfor et blueprint?

Den eksisterende personality-editor er fri tekst. Det er fleksibelt, men gør det let at ende med en generisk eller inkonsistent persona, som kun vanskeligt kan reproduceres mellem revisioner.

Blueprint v1 opdeler derfor personen i to forskellige evidensklasser:

1. **Kommunikationsadfærd** — eksplicit menneskeligt authored/reviewed.
2. **Embodiment / mannerisms** — kan groundes i observerbare BodyPrint-data fra den konkrete `.mrbody`.

BodyRig må ikke bruge kropsbygning, ansigt eller bevægelsesmønstre som bevis for indre tanker, værdier, minder, relationer eller andre mentale/personlige egenskaber.

## Kommunikationsdimensioner

Alle værdier er 0..1:

- `directness`
- `warmth`
- `playfulness`
- `formality`
- `verbosity`
- `initiative`

De er altid markeret som `operator-authored`.

Blueprintet kompilerer dimensionerne deterministisk til eksisterende ModelRig system-instructions. Det betyder, at samme blueprint giver samme personality-kandidattekst og dermed samme assembly fingerprint, så længe de øvrige kandidater er uændrede.

## Observerbar embodiment

Hvis blueprintet bygges mod en konkret `.mrbody` og dens `body-rXXXX`, seedes følgende værdier fra den validerede BodyPrint:

- `movement_energy` <- `motion.energy`
- `gesture_frequency` <- `motion.gesture_frequency`
- `gesture_amplitude` <- `motion.gesture_amplitude`
- `head_motion` <- `motion.head_motion`
- `gaze_strength` <- `expression.gaze_strength`
- `speech_motion` <- `expression.speech_motion`

Manglende BodyPrint-felter bliver neutral `0.5`; BodyRig opfinder ikke observationer.

Disse værdier beskriver **mannerisms**, ikke indre personlighed. De bliver lagt i candidate `style_notes`, så nuværende ModelRig-audition kan se grounding, og senere BodyRig/Kaliv-runtime kan bruge samme værdier til faktisk bevægelsesstil.

## CLI

Uden en body candidate:

```powershell
bodyrig-personality-blueprint `
  --default-language da `
  --directness 0.75 `
  --warmth 0.70 `
  --playfulness 0.65 `
  --formality 0.25 `
  --verbosity 0.35 `
  --initiative 0.65 `
  --authored-notes "Tør, underspillet humor. Ikke serviceagtig." `
  --out personality-blueprint.json
```

Med observerbar embodiment fra en konkret body candidate:

```powershell
bodyrig-personality-blueprint `
  --default-language da `
  --directness 0.75 `
  --warmth 0.70 `
  --playfulness 0.65 `
  --formality 0.25 `
  --verbosity 0.35 `
  --initiative 0.65 `
  --body-package "C:\path\person.mrbody" `
  --body-revision body-r0003 `
  --out personality-blueprint.json
```

CLI-resultatet indeholder både:

- den validerede `bodyrig-personality-blueprint` v1,
- den kompilerede eksisterende personality candidate:
  - `instructions`
  - `default_language`
  - `style_notes`

Output er create-only, så et tidligere blueprint ikke kan overskrives lydløst.

## Trust boundary

Blueprint er **ikke** en aktiv person og må ikke omgå den eksisterende Person Revision-gate.

Den normale kæde er fortsat:

```text
Blueprint
  -> kompiler personality candidate
  -> gem ny personality-rXXXX
  -> vælg body-rXXXX + voice-rXXXX + personality-rXXXX
  -> beregn exact assembly fingerprint
  -> kør faktisk ModelRig audition
  -> VoiceRig siger præcis ModelRig-svaret
  -> menneskelig compatibility review
  -> person-rXXXX
  -> atomisk aktivering
```

En ny body candidate ændrer ikke automatisk eksisterende personality. Hvis mannerism-grounding skal følge en ny body revision, bygges en ny blueprint/personality candidate og auditioneres igen.

## Næste lag

Blueprint v1 gør personality authoring struktureret og binder observerbar kropsadfærd korrekt til BodyRig-data. Senere lag kan udvide med eksempelbaseret kommunikationsstil fra eksplicit godkendte tekst/transkript-kilder, men sådanne observationer skal have egen provenance og må ikke blandes sammen med video-baseret motion eller med påstande om personens private mentale tilstand.
