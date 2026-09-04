# ModelRig Person Profile v1

BodyRig UI arbejder med **personer**, ikke med én global krop.

En person har én stabil identitet. Krop, stemme og personlighed versionsstyres hver for sig, men de **aktiveres aldrig hver for sig**. Den aktive person er altid en samlet, faktisk auditioneret og compatibility-godkendt **Person Revision**.

```text
Person
  person_id (stabilt)
  display_name
  aliases
  source binding (fx Stash performer-id)

  Component candidates
    body-r0001        -> .mrbody / bodyid-... / SHA-256
    voice-r0001       -> VoiceRig .mrvoice / voice-id / SHA-256
    personality-r0001 -> ModelRig persona instructions

  Approved person revisions
    person-r0001 = body-r0001 + voice-r0001 + personality-r0001
    person-r0002 = body-r0002 + voice-r0001 + personality-r0002

  active_person_revision -> person-r0002
```

## Identity rule

`person_id` er den eneste stabile personidentitet. Den må **ikke** være BodyRigs `bodyid-*`, VoiceRigs voice-id, Stash performer-id, display name eller alias.

Format:

```text
person-<32 lowercase hex>
```

ID'et genereres tilfældigt én gang og ændres ikke, når komponenter eller Person Revisions ændres.

## Person record

Den lokale registry-record er `modelrig-person-profile` v1 og indeholder:

- `person_id`, display name, aliases og optional Stash source binding,
- `body_revisions`,
- `voice_revisions`,
- `personality_revisions`,
- `person_revisions`,
- `active_person_revision`.

`source` kan være `null`. Person Profile gemmer ikke ModelRig-token, Stash-token eller andre credentials.

## Component revision rule

Alle komponentændringer skaber en ny immutable kandidat:

```text
body-r0001
voice-r0001
personality-r0001
```

En kandidat må **ikke** automatisk ændre den aktive person.

### Body revision

Binder til canonical `bodyid-*`, `.mrbody` SHA-256, package-path/preview og feedback. BodyRig re-hasher og validerer `.mrbody` igen før audition og reaktivering.

### Voice revision

VoiceRig ejer voice-artifactet. BodyRig læser VoiceRigs lokale validerede bibliotek og binder kandidaten til:

- VoiceRig `voice_id`,
- konkret safe `.mrvoice`-pakkenavn,
- SHA-256 af de faktiske package-bytes,
- feedback.

Før audition og reaktivering downloader BodyRig den samme package fra VoiceRig over loopback og re-hasher bytes. Et nyt artifact under samme filnavn kan derfor ikke stille og roligt overtage en gammel voice-revision.

### Personality revision

ModelRig ejer personality-execution. Kandidaten indeholder mindst persona/system instructions, default language, optional style notes og feedback.

**Statisk visning af instructions er ikke compatibility-evidence.** En personality-kandidat skal køres gennem ModelRig i den eksakte Person Assembly, og det resulterende svar skal høres med den valgte VoiceRig-stemme, før Person Revision kan godkendes.

## Exact audition assembly

Før audition beregner BodyRig et deterministisk `bodyrig-person-assembly` v1 for præcis de tre valgte kandidater.

Fingerprintet binder:

- `person_id`,
- body revision + `body_id` + `.mrbody` SHA-256,
- voice revision + `voice_id` + `.mrvoice` pakkenavn + SHA-256,
- personality revision + SHA-256 af instructions/style notes + default language.

```text
assembly_fingerprint = sha256(canonical assembly JSON)
```

Skiftes body, voice eller personality, ændres fingerprintet og en tidligere audition kan ikke genbruges.

## ModelRig-executed audition

BodyRig bruger ModelRigs eksisterende lokale `POST /api/v1/chat` uden at ændre ModelRigs globale/default state.

For den valgte personality sendes én isoleret request:

```text
system = personality instructions + style + default language
user   = operatorens audition-prompt
stream = false
```

ModelRigs faktiske reply sendes derefter til VoiceRig, som syntetiserer **netop det svar** med den hash-bundne `.mrvoice`.

Audition-rummet skal derfor vise/høre samme kombination:

1. body-preview fra den hash-validerede `.mrbody`,
2. den valgte personality-kilde,
3. det faktiske ModelRig-svar,
4. VoiceRig-WAV af præcis det ModelRig-svar.

Compatibility-review låses, indtil body-preview er loadet, personality-kilden er vist, ModelRig-svaret er modtaget og VoiceRig-WAV'en er afspillet til ende. Ændres kandidat, ModelRig-model eller audition-prompt, nulstilles reviewet.

### Execution trust boundary

Standard ModelRig endpoint er loopback `http://127.0.0.1:8080`; standard VoiceRig endpoint er loopback `http://127.0.0.1:8765`.

BodyRig kalder først ModelRig unauthenticated `/healthz` og kræver `service=modelrig-server` samt en gyldig `version`. **Først derefter** må bearer-tokenet bruges mod beskyttede ModelRig-routes. En fremmed lokal proces på porten får derfor ikke tokenet blot ved at svare på en TCP/HTTP-forbindelse.

Umiddelbart før TTS kalder den virkelige VoiceRig-klient `/api/health` og kræver `ok=true`, `service=voicerig` samt en gyldig `version`. Kun derefter udføres `/api/tts/synthesize`.

De validerede runtime-identiteter registreres request-lokalt og forbruges, når audition-receiptet materialiseres. Mangler én af runtime-identiteterne, skrives der ingen audition-evidence.

`MODELRIG_TOKEN` er process-env/transport-only og må ikke ende i Person Profile, audition receipt, assembly receipt eller andre artifacts.

## Create-only audition evidence

En gennemført audition materialiserer:

```text
audition-receipts/<person_id>/audition-<32hex>.json
audition-receipts/<person_id>/audition-<32hex>.wav
```

`bodyrig-person-audition` v1 binder:

- `person_id`,
- `assembly_fingerprint`,
- `modelrig_service = modelrig-server`,
- `modelrig_version` fra det validerede ModelRig health-svar,
- valgt ModelRig-model,
- `voicerig_service = voicerig`,
- `voicerig_version` fra VoiceRig health-preflightet umiddelbart før synthesis,
- SHA-256 af audition-prompten,
- SHA-256 af ModelRig-replyet,
- SHA-256 af VoiceRig-WAV'en,
- create timestamp og `complete=true`.

Raw prompt og raw reply gemmes ikke i receiptet; UI kan vise replyet fra den aktuelle request, men den permanente evidence gemmer kun hashes. ModelRig-token, URL og VoiceRig-secrets gemmes aldrig.

Audio bytes re-hashes ved senere approval/reaktivering. Manipuleres WAV'en eller receiptets runtime-provenance, bliver auditionen ugyldig i den assembly-receipt-kæde, der hash-binder audition-receiptet.

## Person Revision — atomic activation unit

En Person Revision binder præcis én eksisterende revision fra hvert lag:

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
    "note": "Samme oplevede person på tværs af krop, stemme og faktisk adfærd."
  }
}
```

Approval-requesten skal medbringe både det auditionerede `assembly_fingerprint` og det konkrete `audition_id`.

Ved approval:

1. re-hasher BodyRig `.mrbody` og VoiceRig `.mrvoice`,
2. genberegner personality-binding og assembly fingerprint,
3. verificerer audition receipt + WAV mod samme fingerprint,
4. kræver alle fire compatibility-kriterier eksplicit `true` og en ikke-tom review-note,
5. opretter Person Revision,
6. skriver assembly receipt v2,
7. aktiverer først derefter bundlet atomisk, hvis requested.

En vurdering som “stemmen virker for ung til kroppen” må derfor ikke godkendes; lav en ny kandidat og kør en ny samlet audition.

## Create-only assembly receipt v2

Godkendte Person Revisions bruger `bodyrig-person-assembly-receipt` **v2** under:

```text
assembly-receipts/<person_id>/person-rXXXX.json
```

Receiptet binder:

- den eksakte assembly fingerprint,
- body/voice/personality bindings,
- `audition_id`,
- SHA-256 af det konkrete audition receipt.

Da den eksakte audition-receipt hash-bindes, bliver ModelRig/VoiceRig service/version, model, prompt/reply-hashes og WAV-hash transitivt en del af den godkendte Person Revision-evidence.

Ved reaktivering revalideres `.mrbody`, `.mrvoice`, personality fingerprint, audition receipt, audition WAV og assembly receipt. Alle skal stadig passe sammen.

Legacy assembly receipt v1 kan læses som historik, men **kan ikke genaktiveres under den nye policy**. Kombinationen skal auditioneres igen, så den får en v2 receipt med faktisk ModelRig/VoiceRig audition-binding.

Kun `active_person_revision` må skifte den aktive profil.

## UI model

Hovednavigationen er **Mine personer**. For hver person vises:

1. **Overblik** — aktiv Person Revision og dens tre komponenter.
2. **Krop** — build, preview, feedback og body-kandidater.
3. **Stemme** — VoiceRig-bibliotek, voice-kandidater og preview.
4. **Personlighed** — personality-kandidater.
5. **Saml person** — vælg body + voice + personality + ModelRig-model + testprompt, kør faktisk audition, review og opret Person Revision.
6. **Historik** — immutable komponent- og Person Revision-historik.

## Feedback flow

Feedback muterer aldrig den aktive person skjult. Den skaber en ny kandidat.

```text
vælg body-kandidat
  + vælg VoiceRig-kandidat
  + vælg personality-kandidat
  + vælg ModelRig-model + audition-prompt
  -> revalidate exact artifacts/text
  -> beregn assembly_fingerprint
  -> ModelRig health/version + personality execution
  -> VoiceRig health/version + TTS af ModelRig-replyet
  -> create-only runtime-bound audition evidence
  -> se body + læs reply + hør WAV
  -> compatibility review
  -> revalidate samme assembly + audition evidence
  -> create-only assembly receipt v2
  -> Godkend Person Revision
  -> atomisk aktivering
```

## Multi-person rule

Der er ingen singleton-person. Biblioteket kan indeholde mange personer samtidig, hver med egen komponent-, audition- og Person Revision-historik. Aktivering af én person må ikke overskrive andre profiler.

ModelRig/Kaliv vælger en person eksplicit og skal anvende den aktive Person Revisions body/voice/personality bindings som ét samlet valg.

## Cross-product ownership

- **BodyRig** ejer body build/preview, Person Profile UI/registry, assembly fingerprint, audition-orchestration og compatibility-bindingen.
- **VoiceRig** ejer `.mrvoice`, voice library og TTS execution.
- **ModelRig** ejer personality/persona execution og LLM-response.
- **Person Revision** er den tværgående, atomiske kompatibilitetsbinding.

`.mrbody` må ikke indeholde personality, og `.mrvoice` må ikke indeholde body/personality blot for at skabe identitet.

## Security/privacy

Person registry, audition receipts og assembly receipts må ikke indeholde Stash API keys, ModelRig bearer tokens eller VoiceRig secrets. Tokens er transport-only.

BodyRig→VoiceRig og BodyRig→ModelRig er loopback-only som standard. Non-loopback integration URLs afvises af klienterne.
