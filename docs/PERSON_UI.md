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

ModelRig ejer senere runtime-execution af personality. BodyRig ejer versions-/assembly-reviewet.

## Saml person

Dette er compatibility-gaten.

1. Vælg én body-, voice- og personality-kandidat.
2. Klik **Forbered audition**.
3. BodyRig revaliderer `.mrbody`, downloader/re-hasher den konkrete `.mrvoice` og hasher personality-indholdet.
4. BodyRig beregner et `assembly_fingerprint` for den eksakte kombination.
5. Se body-previewet.
6. Hør den valgte stemme. En stemmeprøve tæller først som gennemgået i UI'et, når audio er afspillet til ende.
7. Læs de valgte personality instructions/stilnoter.
8. Først derefter åbnes compatibility-reviewet.
9. Bekræft:
   - krop ↔ stemme,
   - stemme ↔ personlighed,
   - krop ↔ personlighed,
   - samlet troværdighed.
10. Skriv review-note og godkend.

Hvis en selector ændres efter audition, nulstilles reviewet.

Ved approval revaliderer serveren de tre bindings igen og kræver samme `assembly_fingerprint`. En ændret body-, voice- eller personality-kandidat kræver ny audition.

## Person Revision

Et godkendt bundle bliver fx:

```text
person-r0007
  = body-r0003
  + voice-r0002
  + personality-r0005
```

BodyRig skriver samtidig en create-only assembly receipt. Kun den samlede `person-r0007` kan blive aktiv.

En gammel godkendt Person Revision kan genaktiveres, men kun efter revalidation af body-/voice-bytes, personality-fingerprint og assembly receipt.

## Flere personer

Der kan ligge mange personer i biblioteket samtidig. En ny Anna-revision påvirker ikke Peter, Sara eller andre profiler.

Det fælles ModelRig-lag skal vælge en `person_id` og anvende personens aktive `person-rXXXX` atomisk. ModelRig må ikke skifte kun voice eller kun personality bag om Person Revision-kontrakten.

## Local-only integration

Standardporte:

- BodyRig: `127.0.0.1:8775`
- VoiceRig: `127.0.0.1:8765`

BodyRig afviser som standard ikke-loopback requests. BodyRig→VoiceRig klienten accepterer kun loopback URL.

Stash-token, ModelRig-token og andre secrets må ikke ende i Person Profile eller assembly receipts.
