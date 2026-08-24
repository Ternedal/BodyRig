# ModelRig Person Profile v1

BodyRig UI arbejder med **personer**, ikke med én global krop.

En person har én stabil identitet. Krop, stemme og personlighed versionsstyres hver for sig, men de **aktiveres aldrig hver for sig**. Den aktive person er altid en samlet, auditioneret og compatibility-godkendt **Person Revision**.

```text
Person
  person_id (stabilt)
  display_name
  aliases
  source binding (fx Stash performer-id)

  Component candidates
    body-r0001        -> .mrbody / bodyid-... / SHA-256
    body-r0002        -> .mrbody / bodyid-... / SHA-256
    voice-r0001       -> VoiceRig .mrvoice / voice-id / SHA-256
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

BodyRig re-hasher og validerer `.mrbody` igen, før kandidaten kan indgå i en audition eller senere reaktivering.

### Voice revision

VoiceRig ejer voice-artifactet. BodyRig må ikke bede operatøren skrive et løst voice-id eller en vilkårlig lokal path.

UI'et læser i stedet VoiceRigs lokale, validerede bibliotek og binder kandidaten til:

- VoiceRig `voice_id`,
- konkret safe `.mrvoice`-pakkenavn,
- SHA-256 af de faktiske package-bytes på bindingstidspunktet,
- feedback.

Før audition og reaktivering downloader BodyRig den samme package fra VoiceRig over loopback og re-hasher bytes. Et nyt artifact under samme filnavn kan derfor ikke stille og roligt overtage en gammel voice-revision.

### Personality revision

Ejes/exekveres af ModelRig og indeholder mindst persona/system instructions, default language, optional style/behaviour notes og feedback.

Personality må ændres uden at rebygge body eller voice, men den nye personality bliver kun aktiv som del af en ny godkendt Person Revision.

## Exact audition assembly

Før compatibility-review beregner BodyRig et deterministisk `bodyrig-person-assembly` v1 for **præcis** de tre valgte kandidater.

Fingerprintet binder:

- `person_id`,
- body revision + `body_id` + `.mrbody` SHA-256,
- voice revision + `voice_id` + `.mrvoice` pakkenavn + SHA-256,
- personality revision + SHA-256 af instructions og style notes + default language.

Resultatet får:

```text
assembly_fingerprint = sha256(canonical assembly JSON)
```

UI'et viser samme assembly som ét audition-rum:

1. den valgte body-preview loades fra hash-valideret `.mrbody`,
2. den valgte VoiceRig-stemme afspilles/syntetiseres fra den hash-bundne `.mrvoice`,
3. den valgte personality vises ved siden af.

Skiftes body-, voice- eller personality-selector, nulstilles audition og compatibility-review.

UI'et åbner først compatibility-reviewet, når body-previewet er loadet, personality'en er vist, og den valgte stemmeprøve er afspillet til ende.

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

Approval-requesten skal samtidig medbringe det `assembly_fingerprint`, som blev auditioneret. Serveren re-hasher body- og voice-artifacts og genberegner personality-bindingen **igen ved approval**. Hvis fingerprintet ikke længere matcher, afvises approval med krav om ny audition.

Person Revision må kun oprettes, når alle fire compatibility-kriterier er **eksplicit true** og review-noten er ikke-tom.

Det betyder fx, at “stemmen virker for ung til kroppen” **ikke** kan godkendes. Brugeren skal først skabe en ny voice- eller body-kandidat og derefter auditionere den nye kombination.

## Create-only assembly receipt

Når en Person Revision er godkendt, materialiserer BodyRig en create-only `bodyrig-person-assembly-receipt` v1 under personbibliotekets `assembly-receipts/<person_id>/person-rXXXX.json`.

Receiptet indeholder den godkendte assembly-fingerprint og de hash-/revisionbindingsdata, der blev reviewet. Det indeholder ikke Stash-token, VoiceRig-secret eller ModelRig-token.

En tidligere `person-rXXXX` må kun reaktiveres gennem UI/API-policyen, hvis:

- body package stadig matcher den registrerede SHA/identity,
- VoiceRig package stadig matcher den registrerede SHA,
- personality-data stadig producerer samme fingerprint,
- create-only receiptet matcher den genberegnede assembly byte-for-byte semantisk.

Gamle historiske Person Revisions uden receipt kan fortsat læses som historik, men de bliver ikke automatisk opgraderet til denne stærkere aktiveringspolicy.

Kun `active_person_revision` må skifte den aktive profil. Et tidligere godkendt `person-rXXXX` med gyldigt receipt kan aktiveres igen atomisk.

## UI model

Hovednavigationen er **Mine personer**. For hver person vises:

1. **Overblik** — aktiv Person Revision og de tre komponenter den binder.
2. **Krop** — build, preview, feedback og body-kandidater.
3. **Stemme** — VoiceRig-bibliotek, hash-bundne voice-kandidater og preview/test.
4. **Personlighed** — personality-kandidater og test.
5. **Saml person** — vælg body + voice + personality, auditionér dem sammen, udfør compatibility-review og opret ny Person Revision.
6. **Historik** — immutable komponent- og Person Revision-historik.

## Feedback flow

Body-feedback må ikke ændre data skjult. BodyRig viser først strukturerede forslag, fx `arm_to_height -0.015`, og en anvendt ændring skaber en ny body-kandidat.

Det samme princip gælder voice og personality: feedback skaber en ny kandidat, ikke en mutation af den aktive person.

Derefter:

```text
vælg body-kandidat
  + vælg VoiceRig-kandidat
  + vælg personality-kandidat
  -> revalidate exact artifact/text bytes
  -> beregn assembly_fingerprint
  -> se + hør + læs samlet
  -> compatibility review
  -> revalidate samme fingerprint
  -> create-only assembly receipt
  -> Godkend Person Revision
  -> atomisk aktivering
```

## Multi-person rule

Der er ingen singleton-person. Biblioteket kan indeholde mange personer samtidig, hver med egen komponent- og Person Revision-historik. Aktivering af én person må ikke overskrive andre profiler.

BodyRig runtime kan stadig have én aktiv krop ad gangen; ModelRig/Kaliv vælger en person eksplicit og anvender den aktive Person Revisions body/voice/personality-bindings som ét samlet valg.

## Cross-product ownership

- **BodyRig** ejer body build/preview/body revisions samt Person Profile UI/registry og assembly/compatibility-bindingen.
- **VoiceRig** ejer `.mrvoice`, voice library og TTS/preview execution.
- **ModelRig** ejer personality/persona execution.
- **Person Revision** er den tværgående, atomiske kompatibilitetsbinding.

`.mrbody` må ikke indeholde personality, og `.mrvoice` må ikke indeholde body/personality blot for at skabe identitet.

## Security/privacy

Person registry og assembly receipts må ikke indeholde Stash API keys, ModelRig tokens eller VoiceRig secrets. Stash performer-id er lokal source metadata; tokens forbliver transport-only.

BodyRig→VoiceRig integration er loopback-only som standard. En ikke-loopback `VOICERIG_URL` afvises af BodyRig-klienten.
