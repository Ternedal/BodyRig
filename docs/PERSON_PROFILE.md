# ModelRig Person Profile v1

BodyRig UI arbejder med **personer**, ikke med én global krop.

En person har én stabil identitet. Krop, stemme og personlighed versionsstyres hver for sig, men de **aktiveres aldrig hver for sig**. Den aktive person er altid en samlet, kompatibilitetsgodkendt **Person Revision**.

```text
Person
  person_id (stabilt)
  display_name
  aliases
  source binding (fx Stash performer-id)

  Component candidates
    body-r0001        -> .mrbody / bodyid-...
    body-r0002        -> .mrbody / bodyid-...
    voice-r0001       -> .mrvoice / voice-id
    personality-r0001 -> ModelRig persona instructions
    personality-r0002 -> ModelRig persona instructions

  Approved person revisions
    person-r0001 = body-r0001 + voice-r0001 + personality-r0001
    person-r0002 = body-r0002 + voice-r0001 + personality-r0002

  active_person_revision -> person-r0002
```

## Identity rule

`person_id` er den eneste stabile personidentitet.

Den må **ikke** være BodyRigs `bodyid-*`, VoiceRigs voice-id, Stash performer-id, display name eller alias.

Format:

```text
person-<32 lowercase hex>
```

ID'et genereres tilfældigt én gang ved oprettelse og ændres ikke, når komponenter eller Person Revisions ændres.

## Person record

Den lokale registry-record er `modelrig-person-profile` v1 og indeholder:

- `person_id`, display name, aliases og optional Stash source binding,
- `body_revisions`,
- `voice_revisions`,
- `personality_revisions`,
- `person_revisions`,
- `active_person_revision`.

`source` kan være `null`; en person kan oprettes uden Stash-binding.

## Component revision rule

Alle komponentændringer skaber en ny immutable kandidatrevision:

```text
body-r0001
voice-r0001
personality-r0001
```

En ny body-, voice- eller personality-revision må **ikke** automatisk ændre den aktive person.

### Body revision

Binder til canonical `bodyid-*`, `.mrbody` SHA-256, package-path/preview og feedback.

### Voice revision

Binder til VoiceRig voice-id, `.mrvoice` SHA-256/path når tilgængelig og feedback.

### Personality revision

Ejes/exekveres af ModelRig og indeholder mindst persona/system instructions, default language, optional style/behaviour notes og feedback.

Personality må ændres uden at rebygge body eller voice, men den nye personality bliver kun aktiv som del af en ny godkendt Person Revision.

## Person Revision — atomic activation unit

En Person Revision binder **præcis én** eksisterende revision fra hvert lag:

```json
{
  "revision_id": "person-r0002",
  "body_revision": "body-r0002",
  "voice_revision": "voice-r0001",
  "personality_revision": "personality-r0002",
  "compatibility_review": {
    "body_voice_match": true,
    "voice_personality_match": true,
    "body_personality_match": true,
    "overall_coherent": true,
    "note": "Samme oplevede person på tværs af krop, stemme og adfærd."
  }
}
```

Person Revision må kun oprettes, når alle fire compatibility-kriterier er **eksplicit true** og review-noten er ikke-tom.

Det betyder fx, at “stemmen virker for ung til kroppen” **ikke** kan godkendes. Brugeren skal først skabe en ny voice- eller body-kandidat og derefter reviewe den nye kombination.

Kun `active_person_revision` må skifte den aktive profil. Et tidligere godkendt `person-rXXXX` kan aktiveres igen atomisk.

## UI model

Hovednavigationen er **Mine personer**. For hver person vises:

1. **Overblik** — aktiv Person Revision og de tre komponenter den binder.
2. **Krop** — build, preview, feedback og body-kandidater.
3. **Stemme** — VoiceRig-kandidater og preview/test.
4. **Personlighed** — personality-kandidater og test.
5. **Saml person** — vælg body + voice + personality, preview/test dem sammen, udfør compatibility-review og opret ny Person Revision.
6. **Historik** — immutable komponent- og Person Revision-historik.

## Feedback flow

Body-feedback må ikke ændre data skjult. BodyRig viser først strukturerede forslag, fx `arm_to_height -0.015`, og en anvendt ændring skaber en ny body-kandidat.

Det samme princip gælder voice og personality: feedback skaber en ny kandidat, ikke en mutation af den aktive person.

Derefter:

```text
vælg body-kandidat
  + vælg voice-kandidat
  + vælg personality-kandidat
  -> preview/test samlet
  -> compatibility review
  -> Godkend person revision
  -> atomisk aktivering
```

## Multi-person rule

Der er ingen singleton-person. Biblioteket kan indeholde mange personer samtidig, hver med egen komponent- og Person Revision-historik. Aktivering af én person må ikke overskrive andre profiler.

BodyRig runtime kan stadig have én aktiv krop ad gangen; ModelRig/Kaliv vælger en person eksplicit og anvender den aktive Person Revisions body/voice/personality-bindings som ét samlet valg.

## Cross-product ownership

- **BodyRig** ejer body build/preview/body revisions og Person Profile UI/registry-kontrakten.
- **VoiceRig** ejer voice artifacts/voice revisions.
- **ModelRig** ejer personality/persona execution.
- **Person Revision** er den tværgående, atomiske kompatibilitetsbinding.

`.mrbody` må ikke indeholde personality, og `.mrvoice` må ikke indeholde body/personality blot for at skabe identitet.

## Security/privacy

Person registry må ikke indeholde Stash API keys, ModelRig tokens eller VoiceRig secrets. Stash performer-id er lokal source metadata; tokenet forbliver transport-only.
