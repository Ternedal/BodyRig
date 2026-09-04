# BodyRig Personality Blueprint v1

BodyRig har allerede én samlet Person-model, hvor **krop**, **stemme** og **personlighed** versionsstyres hver for sig og først aktiveres efter en faktisk ModelRig + VoiceRig audition. Personality Blueprint ændrer ikke den model. Det er et authoring- og grounding-lag foran den eksisterende `personality-rXXXX` kandidat.

## Hvorfor et blueprint?

Den eksisterende personality-editor er fri tekst. Det er fleksibelt, men gør det let at ende med en generisk eller inkonsistent persona, som kun vanskeligt kan reproduceres mellem revisioner.

Blueprint v1 opdeler derfor personen i tre forskellige typer materiale:

1. **Kommunikationsadfærd** — eksplicit menneskeligt authored/reviewed.
2. **Stileksempler** — operator-godkendte replikker, der kun bruges som few-shot eksempler på ordvalg, rytme og conversational texture.
3. **Embodiment / mannerisms** — kan groundes i observerbare BodyPrint-data fra den konkrete `.mrbody`.

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

### Style exemplars

Blueprintet kan indeholde op til 12 operator-godkendte eksempelreplikker. De må bruges af ModelRig til at efterligne:

- ordvalg,
- sætningsrytme,
- tørhed/legende tone,
- conversational texture.

Compiler-instruktionen siger eksplicit, at **faktuel information i eksemplerne ikke er aktuelle facts, biografi eller minder**. Et eksempel som “Jeg elskede den ferie i Rom” må derfor påvirke phrasing, men må ikke skabe et minde om en Rom-ferie.

Blueprintets canonical SHA-256 lægges i den kompilerede `style_notes`. Den eksisterende Person Assembly hasher allerede style-notes, så en senere godkendt Person Revision bliver transitivt bundet til præcis det blueprint, der skabte kandidaten, uden at ændre Person Profile-schemaet.

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
  --style-example "Ja ja, det skal nok gå." `
  --style-example "Det er altså ikke verdens undergang." `
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

### Gem direkte som personality-kandidat

CLI'en kan skrive den kompilerede kandidat direkte ind i det eksisterende Person Profile-register. Der oprettes fortsat kun en **candidate**; intet aktiveres.

```powershell
bodyrig-personality-blueprint `
  --person-library "$env:LOCALAPPDATA\BodyRig\people" `
  --person-id person-0123456789abcdef0123456789abcdef `
  --body-revision body-r0003 `
  --directness 0.75 `
  --warmth 0.70 `
  --style-example "Ja ja, det skal nok gå." `
  --feedback "Første guided personality blueprint" `
  --save-candidate `
  --out "$env:LOCALAPPDATA\BodyRig\personality-blueprints\candidate-01.json"
```

Når `--person-library` + `--person-id` bruges sammen med `--body-revision`, resolver CLI'en selv den `.mrbody`, der er registreret på den konkrete body revision, og validerer pakken før BodyPrint-grounding.

`--save-candidate` kræver `--out`, så authored blueprint-materialet bevares som create-only evidence ved siden af den nye `personality-rXXXX`.

CLI-resultatet indeholder:

- den validerede `bodyrig-personality-blueprint` v1,
- den kompilerede eksisterende personality candidate:
  - `instructions`
  - `default_language`
  - `style_notes`, inkl. `blueprint_sha256`,
- en seks-scenarie audition suite,
- evt. det oprettede `personality-rXXXX` id.

Output er create-only, så et tidligere blueprint ikke kan overskrives lydløst.

## Personality audition suite

Én “præsenter dig selv”-prompt er ikke nok til at vurdere en persona. Blueprint-resultatet indeholder derfor seks anbefalede audition-scenarier:

1. naturlig introduktion,
2. mild uenighed,
3. lille hverdagsfejl — varme/humor,
4. initiativ i en åben situation,
5. falsk hukommelsespræmis — må ikke opfinde fælles minder,
6. ukendt personlig erfaring — må ikke opfinde oplevelser.

Suiten er **ikke activation authority**. Den er et review-redskab og kræver fortsat menneskelig vurdering. Den nuværende Person Revision-gate ændres ikke af blueprint-PR'en.

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

Blueprint v1 gør personality authoring struktureret, understøtter sikre few-shot stil-eksempler og binder observerbar kropsadfærd korrekt til BodyRig-data. Et senere lag kan hente kommunikationsstil fra eksplicit godkendte transkript-kilder med egen provenance. Det lag skal fortsat skelne observerbar sproglig stil fra påstande om personens private mentale tilstand eller biografi.
