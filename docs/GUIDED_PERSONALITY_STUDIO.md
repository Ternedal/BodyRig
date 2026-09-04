# BodyRig Guided Personality Studio

Guided Personality Studio er den interaktive authoring-flade oven på BodyRigs eksisterende Personality Blueprint og Person Revision-model.

Åbn efter normal BodyRig-start:

```text
http://127.0.0.1:8775/ui/personality_guided.html
```

Du kan også vælge en person direkte:

```text
http://127.0.0.1:8775/ui/personality_guided.html?person_id=person-...
```

## Hvad UI'en authorer

Kommunikationsadfærd sættes eksplicit på seks 0..1-dimensioner:

- direktehed,
- varme,
- legesyge/humor,
- formalitet,
- detaljeringsgrad,
- initiativ.

Derudover kan operatoren angive:

- standardsprog,
- authored notes,
- direkte operator-authored style exemplars,
- valgfri konkret `body-rXXXX` som mannerism-grounding,
- en transcript candidate report + dens eksplicitte approval receipt.

Det samlede antal direkte + transcript-godkendte style exemplars er højst 12.

Hvis en body revision vælges, validerer BodyRig den registrerede `.mrbody` og dens SHA-256 og bruger kun observerbare BodyPrint-felter som movement energy, gesture frequency/amplitude, head motion, gaze og speech-motion. Kommunikationspersonlighed bliver fortsat ikke infereret fra krop eller video.

## Browser-import af transcript evidence

Guided Studio kan importere de to JSON-filer fra transcript-workflowet:

1. `bodyrig-personality-exemplar-candidates` report,
2. `bodyrig-personality-exemplar-approval` receipt.

Browseren læser JSON-indholdet lokalt via File API. **Lokale filstier sendes ikke til BodyRig.** Requesten indeholder selve JSON-objekterne.

BodyRig stoler ikke på browserens status. Ved hvert preview/save:

- candidate report valideres mod sin v1-kontrakt,
- approval receipt valideres mod sin v1-kontrakt,
- report canonical SHA-256 skal matche receiptens binding,
- alle selected indexes skal eksistere,
- approved exemplar-tekst skal matche præcis de valgte indexes,
- speaker identity og style use skal allerede være eksplicit godkendt.

En report uden approval eller approval uden report afvises fail-closed.

## Preview er non-mutating

`POST /api/v1/people/{person_id}/personality/guided/preview`

returnerer:

- normalized blueprint,
- blueprint SHA-256,
- kompilerede ModelRig instructions/style notes,
- evt. style evidence hashes + approved count,
- seks-scenarie audition suite.

Preview skriver hverken blueprint-evidence, transcript-evidence eller en personality revision.

UI'en binder preview til den præcise request. Ændres slider, body grounding, sprog, notes, direkte style example eller de importerede evidence-objekter, låses Save igen indtil et nyt preview er bygget.

## Gem kandidat

`POST /api/v1/people/{person_id}/personality/guided/revisions`

følger denne rækkefølge:

1. load og valider Person Profile,
2. verifier evt. transcript report + approval,
3. valider evt. exact body revision + `.mrbody` bytes,
4. byg og valider Personality Blueprint,
5. skriv evt. immutable transcript report/approval evidence,
6. skriv immutable blueprint-evidence,
7. opret en almindelig `personality-rXXXX` candidate.

Blueprint-evidence ligger separat fra Person Profile-schemaet:

```text
<people-root>/personality-blueprints/<person-id>/<blueprint-sha256>.json
```

Verificeret transcript evidence gemmes canonical og content-addressed:

```text
<people-root>/personality-style-evidence/<person-id>/reports/<report-sha256>.json
<people-root>/personality-style-evidence/<person-id>/approvals/<approval-sha256>.json
```

Samme evidence må genbruge præcis samme immutable digest-fil. En digest-path med andre bytes afvises fail-closed.

Den kompilerede candidates `style_notes` indeholder:

- `blueprint_sha256=<...>`,
- ved transcript evidence: `style_report_sha256=<...>`,
- ved transcript evidence: `style_approval_sha256=<...>`.

Person Assembly-fingerprintet inkluderer personality style notes. Dermed er senere audition og Person Revision transitivt bundet til både blueprint og den præcise transcript review/approval evidence.

## Ingen direkte aktivering

Guided Studio kan kun oprette en personality candidate. Det har ingen component-activation endpoint og kan ikke skabe en aktiv person.

Den eksisterende authority chain gælder fortsat:

```text
Transcript sources (valgfri)
  -> candidate report
  -> explicit speaker/style approval
  -> Guided Blueprint
  -> personality-rXXXX candidate
  -> vælg exact body + voice + personality
  -> ModelRig execution
  -> VoiceRig siger præcis ModelRig-svaret
  -> se krop + se personality + hør hele svaret
  -> human compatibility review
  -> Person Revision
  -> atomic activation
```

## Transcript-workflow

Transcript-derived replikker skal fortsat først gennem den provenance-komplette extraction/approval-kæde:

```text
bodyrig-personality-exemplars
  -> candidate report
  -> bodyrig-personality-approve-exemplars
  -> approval receipt
```

Forskellen er nu, at de to færdige evidencefiler kan trækkes direkte ind i Guided Studio, så man ikke behøver bruge blueprint-CLI'en bagefter. UI'en laver **ikke** approval selv og kan derfor ikke omgå speaker/style-gaten.
