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
- op til 12 direkte authored style exemplars,
- valgfri konkret `body-rXXXX` som mannerism-grounding.

Hvis en body revision vælges, validerer BodyRig den registrerede `.mrbody` og dens SHA-256 og bruger kun observerbare BodyPrint-felter som movement energy, gesture frequency/amplitude, head motion, gaze og speech-motion. Kommunikationspersonlighed bliver fortsat ikke infereret fra krop eller video.

## Preview er non-mutating

`POST /api/v1/people/{person_id}/personality/guided/preview`

returnerer:

- normalized blueprint,
- blueprint SHA-256,
- kompilerede ModelRig instructions/style notes,
- seks-scenarie audition suite.

Preview skriver hverken blueprint-evidence eller en personality revision.

UI'en binder preview til den præcise request. Ændres slider, body grounding, sprog, notes eller style example, låses Save igen indtil et nyt preview er bygget.

## Gem kandidat

`POST /api/v1/people/{person_id}/personality/guided/revisions`

følger denne rækkefølge:

1. load og valider Person Profile,
2. valider evt. exact body revision + `.mrbody` bytes,
3. byg og valider Personality Blueprint,
4. skriv immutable blueprint-evidence,
5. opret en almindelig `personality-rXXXX` candidate.

Blueprint-evidence ligger separat fra Person Profile-schemaet:

```text
<people-root>/personality-blueprints/<person-id>/<blueprint-sha256>.json
```

Samme blueprint må genbruge præcis samme immutable evidence-fil. En digest-path med andre bytes afvises fail-closed.

Den kompilerede candidates `style_notes` indeholder allerede `blueprint_sha256=<...>`, og Person Assembly-fingerprintet inkluderer personality style notes. Dermed er senere audition og Person Revision transitivt bundet til blueprint-evidencen.

## Ingen direkte aktivering

Guided Studio kan kun oprette en personality candidate. Det har ingen component-activation endpoint og kan ikke skabe en aktiv person.

Den eksisterende authority chain gælder fortsat:

```text
Guided Blueprint
  -> personality-rXXXX candidate
  -> vælg exact body + voice + personality
  -> ModelRig execution
  -> VoiceRig siger præcis ModelRig-svaret
  -> se krop + se personality + hør hele svaret
  -> human compatibility review
  -> Person Revision
  -> atomic activation
```

## Transcript-eksempler

Den første Guided Studio-flade accepterer kun direkte operator-authored style examples. Transcript-derived replikker skal fortsat gennem den provenance-komplette kæde:

```text
bodyrig-personality-exemplars
  -> candidate report
  -> bodyrig-personality-approve-exemplars
  -> approval receipt
  -> bodyrig-personality-blueprint --style-report ... --style-approval ...
```

UI-import af verificerede transcript approval receipts er et separat næste lag; UI'en må ikke skabe en genvej uden om speaker/style approval-gaten.
