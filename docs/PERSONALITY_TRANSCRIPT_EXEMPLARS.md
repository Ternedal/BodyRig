# BodyRig transcript → style exemplar candidates

Dette lag gør det lettere at bygge en personlighed, der lyder som den konkrete person frem for som en generisk prompt.

Det **kloner ikke personlighed automatisk**. Det udtrækker kun reviewbare replikker fra operator-leverede transkripter, så et menneske kan vælge hvilke formuleringer der må bruges som style exemplars i `bodyrig-personality-blueprint`.

## Input

`bodyrig-personality-exemplars` accepterer 1..20 UTF-8 tekstfiler. Typiske formater:

- `.txt`
- `.srt`
- `.vtt`

BodyRig udfører ikke speech-to-text i dette trin. Det er bevidst: transcript-kilden skal være eksplicit og reviewbar, og speaker attribution skal ikke gættes skjult.

Hver kilde må højst være 4 MiB.

## Hvad parseren gør

- fjerner UTF-8 BOM,
- normaliserer linjeskift og whitespace,
- fjerner SRT/VTT timestamps og cue-numre,
- fjerner simple HTML/subtitle-tags,
- splitter almindelig single-line tekst i sætninger,
- deduplikerer replikker case-insensitivt,
- beholder højst 200 kandidater,
- foreslår højst 12 jævnt fordelte kandidater til review.

Forslagene er deterministiske. Samme input-bytes og samme limit giver samme kandidatrapport.

## Provenance og privacy

Rapporten gemmer ikke filstier. Den indeholder i stedet SHA-256 for hver transcript-kilde, så rapporten kan bindes til de konkrete input-bytes.

**Rapporten indeholder transcript-uddrag.** Den er derfor path-free, men ikke indholdsfri eller nødvendigvis privatlivsneutral. Opbevar den som privat BodyRig/personality-evidence, hvis transkripterne ikke er offentlige.

Rapporten erklærer eksplicit:

```json
{
  "operator_review_required": true,
  "speaker_identity_authority": false,
  "personality_authority": false,
  "content_semantics": "style-only-not-biography-or-memory"
}
```

Det betyder:

- BodyRig påstår ikke, at en bestemt replik med sikkerhed tilhører den ønskede person.
- BodyRig påstår ikke, at en replik beviser en indre personlighedsegenskab.
- Faktuelt indhold i en replik må ikke blive til biografi eller hukommelse i ModelRig.

Hvis en transcript-fil indeholder flere talere, skal operatoren selv vælge de replikker, der faktisk tilhører personen. Automatisk speaker diarization er ikke en del af denne authority boundary.

## CLI

```powershell
bodyrig-personality-exemplars `
  .\transcripts\clip-01.srt `
  .\transcripts\clip-02.vtt `
  .\transcripts\interview.txt `
  --suggested-limit 12 `
  --out "$env:LOCALAPPDATA\BodyRig\personality-exemplars\review-01.json"
```

`--out` er create-only. Et eksisterende review kan ikke overskrives lydløst.

## Fra kandidater til Personality Blueprint

1. Kør transcript extractor.
2. Gennemgå `candidates` / `suggested_exemplars` manuelt.
3. Bekræft speaker identity for hver valgt replik.
4. Vælg kun replikker, der er nyttige for **stil**: rytme, ordvalg, humor, direktehed, typiske vendinger.
5. Feed de godkendte replikker ind i blueprintet med gentagne `--style-example`.
6. Gem blueprintet som en ny `personality-rXXXX` candidate.
7. Kør den normale BodyRig ModelRig/VoiceRig audition og human compatibility review.

Eksempel:

```powershell
bodyrig-personality-blueprint `
  --person-id person-0123456789abcdef0123456789abcdef `
  --body-revision body-r0003 `
  --directness 0.75 `
  --warmth 0.70 `
  --playfulness 0.65 `
  --formality 0.25 `
  --verbosity 0.35 `
  --initiative 0.65 `
  --style-example "Ja ja, det skal nok gå." `
  --style-example "Det er altså ikke verdens undergang." `
  --save-candidate `
  --out "$env:LOCALAPPDATA\BodyRig\personality-blueprints\candidate-01.json"
```

## Hvad dette flytter

Før dette lag var Personality Blueprint stadig primært sliders + fri tekst. Transcript-exemplars giver et reproducerbart few-shot materiale, der kan gøre ModelRig-output mindre generisk og mere sprogligt genkendeligt, uden at BodyRig behøver at opfinde egenskaber eller minder.

Næste naturlige trin er et review-UI, hvor de foreslåede replikker kan godkendes/afvises direkte i Person-værktøjet og derefter bruges til at bygge en ny personality candidate.
