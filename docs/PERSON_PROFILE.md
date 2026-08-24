# ModelRig Person Profile v1

BodyRig UI arbejder med **personer**, ikke med én global krop.

En person har en stabil identitet, mens krop, stemme og personlighed er uafhængige, versionsstyrede lag.

```text
Person
  person_id (stabilt, random UUID-baseret)
  display_name
  aliases
  source binding (fx Stash performer-id)

  Body revisions
    body r1 -> .mrbody / bodyid-...
    body r2 -> .mrbody / bodyid-...
    active/approved -> r2

  Voice revisions
    voice r1 -> .mrvoice / voice-id
    voice r2 -> .mrvoice / voice-id
    active/approved -> r2

  Personality revisions
    personality r1 -> ModelRig persona instructions
    personality r2 -> ModelRig persona instructions
    active/approved -> r2
```

## Identity rule

`person_id` er den eneste stabile personidentitet.

Den må **ikke** være:

- BodyRigs `bodyid-*` (content-derived og kan ændre sig ved ny body revision),
- VoiceRigs voice-id,
- Stash performer-id,
- display name eller alias.

Formatet er:

```text
person-<32 lowercase hex>
```

og genereres tilfældigt én gang ved oprettelse.

## Person record

Den lokale registry-record er `modelrig-person-profile` v1:

```json
{
  "format": "modelrig-person-profile",
  "version": 1,
  "person_id": "person-0123456789abcdef0123456789abcdef",
  "display_name": "Eksempel",
  "aliases": ["Eksempel alias"],
  "created_utc": "2026-08-24T14:00:00Z",
  "updated_utc": "2026-08-24T14:00:00Z",
  "source": {
    "kind": "stash-performer",
    "performer_id": "123"
  },
  "active": {
    "body_revision": null,
    "voice_revision": null,
    "personality_revision": null
  },
  "body_revisions": [],
  "voice_revisions": [],
  "personality_revisions": []
}
```

`source` kan være `null`; en person kan oprettes uden Stash-binding.

## Revision rule

Alle ændringer skaber en ny revision. Tidligere revisioner overskrives ikke.

Et revisions-id er lokalt stabilt i profilen:

```text
body-r0001
voice-r0001
personality-r0001
```

En revision har mindst:

- revision-id,
- create timestamp,
- status (`draft`, `approved`, `superseded`),
- menneskelig note/feedback,
- binding til det konkrete artifact eller persona-indhold.

### Body revision

Binder til:

- canonical BodyRig `bodyid-*`,
- `.mrbody` SHA-256,
- lokal package-path når den findes,
- optional preview/thumbnail,
- feedback som førte til revisionen.

En ny body-revision ændrer **ikke** `person_id`.

### Voice revision

Binder til:

- VoiceRig voice-id,
- `.mrvoice` SHA-256 når tilgængelig,
- lokal package reference,
- feedback/note.

En ny voice-revision ændrer **ikke** `person_id`.

### Personality revision

Personlighed ejes logisk af ModelRig, ikke `.mrbody` eller `.mrvoice`.

Revisionen indeholder den ModelRig-persona-kontrakt, som skal bruges for personen. V1 skal mindst kunne bære:

- `instructions` / system-persona,
- default language,
- optional style/behaviour notes,
- feedback/note.

En personality-revision må kunne ændres uden at rebygge body eller voice.

## UI model

BodyRig UI's hovednavigation er **Mine personer**.

For hver person vises:

1. **Overblik** — navn, Stash-binding, aktiv body/voice/personality og samlet readiness.
2. **Krop** — build fra Stash, revisioner, preview, feedback og ny revision.
3. **Stemme** — tilknyttede VoiceRig-profiler/revisioner og aktiv stemme.
4. **Personlighed** — ModelRig persona-revisioner, redigering og test.
5. **Historik** — immutable revisionshistorik og hvem/hvad der er aktivt.

## Body feedback flow

Canonical flow:

```text
skriv navn
  -> vælg/opret person
  -> find Stash performer
  -> Byg krop
  -> progress
  -> 3D/thumbnail preview
  -> skriv feedback
  -> BodyRig viser konkrete foreslåede parameterændringer
  -> bruger godkender ændringerne
  -> Lav revision
  -> preview r2
  -> Godkend r2
```

Fri tekst må **ikke** ændre body-data skjult. BodyRig skal først vise de strukturerede ændringer, der vil blive anvendt.

BodyPrint-felter som kan bruges til kontrollerede V1-tilretninger omfatter bl.a. `height_scale`, `shoulder_to_height`, `hip_to_height`, `arm_to_height`, `leg_to_height` samt motion/expression/runtime-parametre. Source-derived high-fidelity geometry må ikke destruktivt overskrives uden en ny revision og tydelig provenance.

## Multi-person rule

Der er ingen global singleton-person.

- biblioteket må indeholde mange personer samtidig,
- hver person har egne revisionsnumre,
- aktivering af én person sletter eller overskriver ikke andre,
- BodyRig runtime kan stadig have én **aktiv** krop ad gangen, men biblioteket er multi-person,
- ModelRig/Kaliv vælger person/profile eksplicit.

## Cross-product ownership

- **BodyRig** ejer body build/preview/body revisions.
- **VoiceRig** ejer voice artifacts/voice revisions.
- **ModelRig** ejer personality/persona execution.
- **Person Profile registry** binder de tre lag sammen via `person_id`.

Ingen komponent må kopiere en anden komponents artifact ind i sit eget format blot for at skabe personidentitet.

## Security/privacy

Person registry må ikke indeholde Stash API keys, ModelRig tokens eller VoiceRig secrets.

Stash performer-id er lokal source metadata; tokenet forbliver transport-only.
