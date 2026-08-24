# BodyRig Person Studio

BodyRig V1 har en lokal browser-UI til at bygge og vedligeholde **flere personer**. UI'et er den normale menneskelige workflow-flade; PowerShell-gates underneden forbliver authority for fysisk clone/release evidence.

## Start på Windows

Fra et clean BodyRig checkout, efter bootstrap af repoets `.venv`:

```powershell
.\start-windows.ps1
```

Launcheren:

- kræver `.venv\Scripts\python.exe` og `.venv\Scripts\bodyrig.exe` fra dette checkout,
- beviser at `.venv` importerer `bodyrig` fra netop `<checkout>\bodyrig\__init__.py`,
- kræver valid Git HEAD og clean checkout,
- starter kun BodyRig på loopback `127.0.0.1:8775`,
- gemmer lokal PID/root/revision launcher-state under `%LOCALAPPDATA%\BodyRig`,
- nægter at genbruge en service på port 8775, hvis den ikke kan bindes til denne launcher/checkouts state,
- åbner `http://127.0.0.1:8775/` i browseren.

Brug `-NoBrowser`, hvis servicen skal startes uden automatisk browseråbning.

## Mine personer

Venstre side er et bibliotek, ikke en singleton-profil. Hver person har stabilt `person_id` og sin egen historik for:

- body-kandidater,
- VoiceRig-kandidater,
- personality-kandidater,
- godkendte Person Revisions.

En kandidat ændrer aldrig den aktive person alene.

## Krop

**Byg ny body-kandidat** bruger personens Stash performer-binding og starter den samme canonical physical pipeline som CLI-flowet. UI'et må ikke omgå `clone-body-from-stash-ready.ps1` eller Gate A.

En færdig build bliver kun `body-rXXXX` kandidat. Den kan previewes og kommenteres.

Fri body-feedback bliver først oversat til synlige, strukturerede forslag. Ukendt feedback ændrer ingenting på et gæt.

## Stemme

Stemmefanen læser VoiceRigs lokale bibliotek over loopback. Brugeren vælger en konkret VoiceRig-stemme i stedet for at skrive voice-id eller filesystem-path manuelt.

Ved binding gemmer BodyRig:

```text
voice-rXXXX
  voice_id
  voice_package (.mrvoice filename)
  package_sha256
```

VoiceRig ejer fortsat selve `.mrvoice` og TTS-runtime.

## Personlighed

Personality-fanen opretter immutable `personality-rXXXX` kandidater med instructions, standardsprog, stilnoter og feedback.

Personality-teksten i BodyRig er **kilde-/versionsdata**, ikke i sig selv bevis på runtime-adfærd. Under samlet audition sender BodyRig den valgte personality som en midlertidig `system`-message til ModelRigs eksisterende `/api/v1/chat`. Det ændrer ikke ModelRigs globale/default personality-state.

ModelRig ejer execution. BodyRig ejer versionering, audition-evidence og den tværgående Person Revision-gate.

## Saml person

Dette er compatibility-gaten.

1. Vælg én body-, voice- og personality-kandidat.
2. Vælg en konkret ModelRig-model.
3. Skriv eller behold auditionens testprompt.
4. Klik **Kør samlet audition**.
5. BodyRig revaliderer `.mrbody`, downloader/re-hasher den konkrete `.mrvoice` og genberegner personality-bindingen.
6. BodyRig beregner et `assembly_fingerprint` for den eksakte body + voice + personality-kombination.
7. BodyRig verificerer først unauthenticated ModelRig `/healthz` som `service=modelrig-server`; først derefter må bearer-tokenet bruges mod protected ModelRig-routes.
8. BodyRig sender den valgte personality som `system` og audition-prompten som `user` til ModelRig uden at ændre global ModelRig-state.
9. Det faktiske ModelRig-svar vises i UI'et.
10. Det samme ModelRig-svar sendes til den hash-bundne VoiceRig-stemme og syntetiseres til WAV.
11. Body-previewet skal være loadet, personality-kilden og ModelRig-svaret skal være vist, og den syntetiserede WAV skal være afspillet til ende.
12. Først derefter åbnes compatibility-reviewet.
13. Bekræft:
   - krop ↔ stemme,
   - stemme ↔ personality/adfærd,
   - krop ↔ personality/adfærd,
   - samlet troværdighed.
14. Skriv review-note og godkend.

Skiftes body, voice, personality eller ModelRig-model efter audition, nulstilles audition og review. Ændres testprompten, nulstilles de også. Et tidligere ModelRig-svar må altså ikke genbruges til en anden kombination eller prompt.

## Audition evidence

En fuldført samlet audition materialiseres create-only som `bodyrig-person-audition` v1. Evidence binder mindst:

- `person_id`,
- `assembly_fingerprint`,
- valgt ModelRig-model,
- SHA-256 af audition-prompten,
- SHA-256 af det faktiske ModelRig-svar,
- SHA-256 af den VoiceRig-WAV, der blev afspillet.

ModelRig bearer-token, Stash-token og andre secrets indgår ikke i evidence.

Approval-requesten medbringer `audition_id`. Serveren revaliderer den valgte assembly og audition-evidence igen; en audition fra en anden assembly kan ikke bruges til approval.

## Person Revision

Et godkendt bundle bliver fx:

```text
person-r0007
  = body-r0003
  + voice-r0002
  + personality-r0005
```

BodyRig skriver samtidig en create-only `bodyrig-person-assembly-receipt` v2. Receiptet binder Person Revision til:

- det eksakte `assembly_fingerprint`,
- body/voice/personality bindings,
- `audition_id`,
- SHA-256 af det create-only audition-receipt, som operatøren faktisk reviewede.

Kun den samlede `person-r0007` kan blive aktiv.

En tidligere Person Revision kan kun genaktiveres efter revalidation af body-/voice-bytes, personality-fingerprint, audition receipt/WAV og assembly receipt. Hvis fx den auditionerede WAV ændres, fejler reaktivering.

Legacy assembly-receipt v1 kan fortsat læses som historik, men mangler den nye runtime-audition-binding og må derfor re-auditioneres før ny aktivering.

## Flere personer

Der kan ligge mange personer i biblioteket samtidig. En ny Anna-revision påvirker ikke Peter, Sara eller andre profiler.

Det fælles ModelRig-lag skal vælge en `person_id` og anvende personens aktive `person-rXXXX` atomisk. ModelRig må ikke skifte kun voice eller kun personality bag om Person Revision-kontrakten.

## Local-only integration

Standardporte:

- BodyRig: `127.0.0.1:8775`
- VoiceRig: `127.0.0.1:8765`
- ModelRig: `127.0.0.1:8080`

BodyRig afviser som standard ikke-loopback requests. BodyRig→VoiceRig og BodyRig→ModelRig klienterne accepterer kun loopback-hosts.

ModelRig kræver bearer-token også på loopback. BodyRig læser det fra `MODELRIG_TOKEN`; standard-URL er `http://127.0.0.1:8080` og kan sættes via `MODELRIG_URL`, men stadig kun til loopback. Tokenet bruges kun til transport og må ikke ende i Person Profile, audition evidence eller assembly receipts.

Stash-token, ModelRig-token og andre secrets må ikke ende i Person Profile, evidence eller portable runtime-assets.
