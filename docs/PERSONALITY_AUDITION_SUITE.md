# BodyRig Personality Audition Suite

Personality Audition Suite er et supplementary review-lag oven på BodyRigs eksisterende exact Person Assembly + ModelRig + VoiceRig audition.

Åbn efter normal BodyRig-start:

```text
http://127.0.0.1:8775/ui/personality_audition_suite.html
```

En bestemt person kan åbnes direkte:

```text
http://127.0.0.1:8775/ui/personality_audition_suite.html?person_id=person-...
```

## Formål

En enkelt fri testprompt er dårlig evidence for, om en personality faktisk føles stabil som den samme person. Suiten kører derfor seks faste scenarier mod:

- samme exact `body-rXXXX`,
- samme exact `voice-rXXXX`,
- samme exact `personality-rXXXX`,
- samme Person Assembly fingerprint,
- samme ModelRig-model,
- samme ModelRig-runtimeversion,
- samme VoiceRig-runtimeversion.

De seks probes dækker:

1. naturlig introduktion,
2. mild uenighed,
3. varme/humor ved et lille uheld,
4. initiativ i en åben situation,
5. modstand mod opdigtet fælles hukommelse,
6. modstand mod opdigtet personlig erfaring.

Suite-definitionen er `bodyrig-personality-audition-suite` v1 og har eksplicit:

```json
{
  "human_review_required": true,
  "activation_authority": false
}
```

## Execution

Runneren kalder den eksisterende:

```text
POST /api/v1/people/{person_id}/auditions
```

én gang pr. probe. Dermed bruger hver probe samme production execution path som den almindelige Person Studio-audition:

```text
exact assembly
  -> ModelRig execution
  -> faktisk reply
  -> VoiceRig synthesis af præcis reply
  -> immutable audition receipt
  -> immutable WAV evidence
```

Hver almindelig audition receipt bærer request-lokal `modelrig_version` og `voicerig_version`. Ved suite-forsegling skal begge runtimeversioner være identiske på tværs af alle seks probes. En serviceopgradering eller et versionsskift midt i suiten får derfor hele forseglingen til at fejle lukket, også selv om ModelRig-modelnavnet er uændret.

Runneren viser både ModelRig-svaret og VoiceRig-lyden pr. probe. Når lydfilen er hørt til ende, markeres den lokalt som hørt i UI'en. Denne lokale UI-markering er ikke authority og gemmes ikke som human approval.

## Forsegling

Når alle seks probes er kørt kan klienten sende deres seks `audition_id`-værdier til:

```text
POST /api/v1/people/{person_id}/personality/audition-suite/reviews
```

Serveren forsegler kun reportet hvis:

- de valgte component revisions stadig bygger det oplyste assembly fingerprint,
- personalityens `default_language` matcher suite-sproget,
- alle seks og kun de seks definerede probe-id'er er til stede,
- hver probe bruger en unik audition receipt,
- hver receipt stadig verificerer mod sin WAV,
- alle receipts har samme exact assembly fingerprint,
- alle receipts er kørt med samme angivne ModelRig-model,
- alle receipts har samme ModelRig-runtimeversion,
- alle receipts har samme VoiceRig-runtimeversion,
- hver receipts `prompt_sha256` matcher den autoritative prompt i suite-definitionen.

Det create-only report ligger her:

```text
<people-root>/personality-suite-reviews/<person-id>/suite-review-<uuid>.json
```

Reportet indeholder ikke rå prompts, replies eller tokens. Det indeholder runtime-provenance og hash-bindinger til:

- suite-definitionen,
- exact ModelRig- og VoiceRig-runtimeversion,
- hver forventet prompt,
- hver audition receipt,
- hvert ModelRig reply,
- hver VoiceRig WAV.

Et eksisterende report kan genverificeres med:

```text
GET /api/v1/people/{person_id}/personality/audition-suite/reviews/{review_id}
```

Genverificering afviser blandt andet ændret component fingerprint, ændret suite-definition, ændrede runtimeversioner, ændret audition receipt og ændret/tampered WAV.

## Authority boundary

Suite-review er med vilje **ikke** koblet ind som en ny release- eller activation-gate endnu.

Den eksisterende Person Revision-kæde forbliver authority:

```text
body + voice + personality candidate
  -> exact assembly
  -> faktisk ModelRig + VoiceRig audition
  -> human compatibility review
  -> Person Revision
  -> atomic activation
```

Suite-reportet er stærkere review-evidence, som kan bruges under den menneskelige vurdering. Først efter fysisk erfaring med flere reelle kloner bør vi beslutte, om hele eller dele af suiten senere skal være obligatorisk activation evidence.


## Handoff til canonical compatibility review

Efter en successful suite-forsegling viser UI'et **Fortsæt til samlet compatibility review**. Linket åbner den canonical Person Studio på `/` og bærer den eksakte komponentkombination, som suiten blev kørt med:

```text
/?person_id=<person-id>
 &body_revision=body-rXXXX
 &voice_revision=voice-rXXXX
 &personality_revision=personality-rXXXX
 &model=<exact-suite-model>
 &tab=assemble
```

Person Studio accepterer kun handoffet, hvis alle tre revisions-ID'er faktisk tilhører den angivne Person. Manglende, fremmede eller stale revisions-ID'er bruges ikke som implicit fallback.

Suite-modellen forvælges kun, hvis det eksakte modelnavn stadig findes i den aktuelle ModelRig-library. Hvis modellen er væk eller omdøbt, nulstiller Person Studio modelvalget og kræver et manuelt valg i stedet for lydløst at vælge en anden model.

Handoffet er **kun selection/navigation**. Suite-reviewets seks executions bliver ikke genbrugt som activation-evidence og åbner ikke compatibility-reviewet. Person Studio nulstiller sin assembly/audition-state og kræver fortsat en ny canonical samlet ModelRig + VoiceRig audition, body-preview, afspilning til ende og eksplicit human compatibility review før en Person Revision kan oprettes eller aktiveres.

Når en ny 6-scenarie-suite startes eller valg ændres, skjules et tidligere handoff igen, så CTA'en ikke kan pege på stale suite-evidence.
