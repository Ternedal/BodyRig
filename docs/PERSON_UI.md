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


Personality-fanens sticky control strip er bevidst read-only og bruger kun eksisterende DOM-state. Kandidat-tælleren tæller kun faktiske `.revision-item`-rækker, så tom-state placeholderen aldrig kan blive til en falsk kandidat. Personality Lab markeres kun klar, når workspace-status er præcis én af de to canonicale states, som det embedded Guided/Audition workspace selv emitterer; vilkårlig eller fejltekst må ikke fortolkes som readiness.


Historik-fanens sticky control strip er tilsvarende fail-closed. `person_app.js` afleder en read-only summary direkte fra den valgte Person Profile: historikrevisioner skal have entydige revision-id'er, `active_person_revision` skal matche præcis én Person Revision, og den aktive Person Revision skal referere til præcis én eksisterende body-, voice- og personality-revision. Strippen læser kun denne eksplicitte data-state fra `historyList.dataset`; den tæller ikke placeholder-DOM og fortolker ikke labels som authority. Manglende/dublerede revisioner eller ufuldstændige bindings vises som ukendt/ugyldig readiness og bliver aldrig grønne.


Drift-fanens Operations control strip er også fail-closed og navigation-only. `operator_control_plane.js` publicerer efter hver authoritative refresh et versioneret, struktureret DOM-snapshot på `operationsControlStrip.dataset`: service-health er kun `ready`, når alle canonicale services både er friske og blocker-frie; execution er kun `ready`, når jobs/launch-feeds er læsbare og ingen aktuelle job/launch-attention findes; Digital Twin er kun `ready`, når de strukturerede `digital_twin_ready=true` og `production_activation=true` booleans begge er til stede. Under refresh sættes hele snapshot'et eksplicit til `checking`. Strippen fortolker ikke summary-tekst, badges eller danske/engelske nøgleord som authority; manglende eller ukendt snapshot-version/state vises som `Ukendt`.

## Saml person

Dette er compatibility-gaten.

1. Vælg én body-, voice- og personality-kandidat.
2. Vælg en konkret ModelRig-model.
3. Skriv eller behold auditionens testprompt.
4. Klik **Kør samlet audition**.
5. BodyRig revaliderer `.mrbody`, downloader/re-hasher den konkrete `.mrvoice` og genberegner personality-bindingen.
6. BodyRig beregner et `assembly_fingerprint` for den eksakte body + voice + personality-kombination.
7. BodyRig verificerer unauthenticated ModelRig `/healthz` som `service=modelrig-server` med en gyldig `version`; først derefter må bearer-tokenet bruges mod protected ModelRig-routes.
8. BodyRig sender den valgte personality som `system` og audition-prompten som `user` til ModelRig uden at ændre global ModelRig-state.
9. Det faktiske ModelRig-svar vises i UI'et.
10. Umiddelbart før TTS verificerer BodyRig VoiceRig `/api/health` som `service=voicerig` med en gyldig `version`.
11. Det samme ModelRig-svar sendes til den hash-bundne VoiceRig-stemme og syntetiseres til WAV.
12. Body-previewet skal være loadet, personality-kilden og ModelRig-svaret skal være vist, og den syntetiserede WAV skal være afspillet til ende.
13. Først derefter åbnes compatibility-reviewet.
14. Bekræft:
   - krop ↔ stemme,
   - stemme ↔ personality/adfærd,
   - krop ↔ personality/adfærd,
   - samlet troværdighed.
15. Skriv review-note og godkend.

Skiftes body, voice, personality eller ModelRig-model efter audition, nulstilles audition og review. Ændres testprompten, nulstilles de også. Et tidligere ModelRig-svar må altså ikke genbruges til en anden kombination eller prompt.

### Deep-link fra Personality Audition Suite

En successful forseglet Personality Audition Suite kan åbne **Saml person** med exact `person_id`, `body-rXXXX`, `voice-rXXXX` og `personality-rXXXX` forvalgt via query-parametre. Person Studio validerer, at de tre revisions-ID'er tilhører den valgte Person, før de sættes.

ModelRig-modelnavnet fra suiten bæres også med. Person Studio venter på den live ModelRig-library og forvælger kun modellen, når det eksakte navn stadig findes. Et stale modelnavn giver tomt modelvalg + operator-advarsel; det må ikke falde tilbage til bibliotekets første model uden menneskelig beslutning.

Deep-linket genbruger **ikke** suite-audition som canonical Person audition. Ved handoff er assembly-state fortsat nulstillet, og **Kør samlet audition** skal køres igen. Review-felterne forbliver låst, indtil den normale body/ModelRig/VoiceRig execution- og afspilningsgate er opfyldt.

## Audition evidence

En fuldført samlet audition materialiseres create-only som `bodyrig-person-audition` v1. Evidence binder mindst:

- `person_id`,
- `assembly_fingerprint`,
- `modelrig_service = modelrig-server`,
- `modelrig_version` fra den health-validerede execution-runtime,
- valgt ModelRig-model,
- `voicerig_service = voicerig`,
- `voicerig_version` fra health-preflightet umiddelbart før synthesis,
- SHA-256 af audition-prompten,
- SHA-256 af det faktiske ModelRig-svar,
- SHA-256 af den VoiceRig-WAV, der blev afspillet.

Execution provenance er request-local og forbruges ved receipt-materialisering. Mangler ModelRig- eller VoiceRig-runtime provenance, bliver audition receipt ikke skrevet. Provenance fra en fejlet/forladt audition må ikke genbruges til en senere audition.

ModelRig bearer-token, Stash-token, URL-credentials og andre secrets indgår ikke i evidence.

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

Da audition-receiptets hash indgår i assembly-receipt v2, er ModelRig/VoiceRig runtime-versionerne transitivt bundet til den godkendte Person Revision.

Kun den samlede `person-r0007` kan blive aktiv.

En tidligere Person Revision kan kun genaktiveres efter revalidation af body-/voice-bytes, personality-fingerprint, audition receipt/WAV og assembly receipt. Hvis fx den auditionerede WAV eller runtime-provenance i receiptet ændres, fejler reaktivering.

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

## Control room navigation

Person Studio's global HUD, command palette and Live Activity drawer reuse already-rendered Person Studio/Drift state and do not introduce a second authority path.

The global HUD now consumes a versioned structured state snapshot published by the Overview cockpit instead of parsing rendered labels such as `6/6`, `Krop —` or revision pills. Person name/revision, pipeline counters and body/voice/personality binding states are explicit `personHud.dataset` fields derived from the authoritative Person Profile + Digital Twin read. Missing, malformed or unknown snapshot state fails closed in the HUD. Drift likewise publishes explicit active/unseen attention counts; the HUD no longer infers operator attention from badge text. The HUD remains presentation/navigation-only and performs no fetches or mutations itself.

Mission Control now follows the same authority boundary. The Overview cockpit publishes a versioned structured mission snapshot with explicit `attention` / `next` / `complete` / `unknown` kind, bounded detail, validated target tab and navigation label. Mission Control no longer scans rendered attention/next-action text, searches for the first clickable node, or infers a target from words such as `voice`, `photoreal`, `M6` or `audition`. Invalid or incomplete snapshots fail closed with a disabled action. Navigation remains presentation-only and uses only the existing Person Studio tabs.

Person Topology is structured on the same principle. Overview publishes source, body, voice, personality, canonical Person Revision and Digital Twin states explicitly on the topology card. The map no longer parses `Person —`, component pills, Stash labels or Digital Twin badge copy. Canonical revision inconsistency is represented explicitly as `invalid`, and Digital Twin only lights as ready from structured `digital_twin_ready=true` plus `production_activation=true`. Missing or malformed topology state fails closed as unknown.

Overview-fanens sticky control strip er nu også kun en structured-state consumer. `person_overview_cockpit.js` publicerer pipeline-completion, canonical Person Revision-binding, Digital Twin readiness og den allerede prioriterede next-action direkte på `overviewControlStrip.dataset`. Strippen parser ikke længere `Komplet`, `Ingen`, `M6 klar` eller den renderede attention/next-action DOM for at træffe readiness-beslutninger. Manglende eller ugyldig state vises som ukendt.

Body-fanens sticky control strip følger samme kontrakt. `person_app.js` publicerer valgt/latest body-preview state fra den aktuelle Person Profile, 4-view review-komponenten publicerer `checking` / `ready` / `missing` / `blocked` direkte fra package-bound review-valideringen, og release-status publicerer production, fidelity, human-review og canonical next-gate state direkte fra release-status payloaden. Strippen læser kun disse versionerede `bodyControlStrip.dataset` felter; den parser ikke badges som `4/4 hash-bundet`, `Review PASS`, `HF-komponenter komplette` eller `Production klar`. Manglende eller delvis state vises fail-closed som ukendt.

Voice-fanens sticky control strip bruger struktureret state. `person_app.js` publicerer VoiceRig-library load-resultat, det aktuelle select-valg, antal voice-kandidater og aktiv canonical voice-binding på `voiceControlStrip.dataset`. Strippen parser ikke `voiceLibraryStatus`, kandidat-DOM eller `Stemme …`-pillens tekst for at afgøre readiness. Library-fejl og initial loading repræsenteres eksplicit som `blocked`/`checking`, mens aktiv binding kun kommer fra den valgte Person Revisions bundle.

The Drift monitor now keeps that rendered state fresh while Person Studio is visible even when the operator is working on Overview, Body, Voice, Personality or another tab. Visible background monitoring uses the same bounded GET/read paths as Drift itself at a slower cadence than the active Drift tab. A browser tab that is actually hidden performs no monitoring reads; it keeps a wake-up timer only and performs an immediate refresh when the page becomes visible again. Changing the selected Person also refreshes the monitor while the page is visible, so global attention cannot remain scoped to the previously selected Person.

When Drift has current operator-attention items, the HUD attention signal opens Live Activity first instead of forcing the operator directly into the full Drift tab. Live Activity mirrors the current bounded attention list and preserves only the existing navigation button for each item. The mirrored button proxies the still-connected source navigation control; if the underlying Drift item has been replaced by a refresh, the drawer refreshes instead of invoking a stale action.


Persisted jobs and operator launches in Live Activity now also expose a navigation-only **Åbn i Drift** drill-down. The drawer strips source-row buttons, audio, progress controls and expanded details from its text mirror, then navigates to the existing Drift tab and scrolls to the exact already-rendered source row. Job/launch rows carry DOM-only identities so a simultaneous Drift re-render can be resolved safely before scrolling. This drill-down never proxies cancel, VoiceRig choice, operator execution or any other mutation control.

Operator attention is delta-aware per canonical Person scope. The first authoritative/read-only monitor result for a Person with no retained browser-local attention state establishes a silent baseline. After that, only newly appearing semantic attention keys — for example a service changing to stale/offline, a job entering an operator-input state, a new Photoreal/Digital Twin gate, or a newly failed canonical launch — are marked as unseen. Person switches restore that Person's own retained active/unseen semantic-key set when it is still fresh; a previously unseen blocker that resolved while the Person was not selected is removed, while a genuinely new current key is marked new.

Unseen attention is highlighted in Drift, the global HUD and Live Activity until the operator opens Live Activity. Opening the drawer acknowledges the current unseen set but does not resolve, hide or mutate the underlying blockers; active attention remains listed until the authoritative/read-only state clears it. Acknowledgement and the last observed semantic-key set are stored browser-locally for up to 24 hours under canonical `person-<32 hex>` / `no-person` scopes, bounded to 64 scopes and validated attention-key prefixes. Persistence contains only active/unseen keys plus timestamps — never blocker text, actions, secrets, backend evidence or execution state. Storage failure degrades to session-only highlighting and never changes authority.

Multiple open Person Studio tabs now consume browser `storage` events for that same bounded attention payload. Cross-tab synchronization is deliberately one-way in authority terms: another tab may clear the local **unseen** marker only when it reports the same active semantic key as already seen; browser storage can never add a new unseen key, replace the current authoritative active-key set, trigger network reads or invoke an action. New blockers still originate only from each tab's own bounded Drift GET monitoring. This prevents an acknowledgement in one tab from leaving stale **NY** indicators in another tab without allowing localStorage to become monitoring authority.

The feature still uses no browser notifications, sound, auto-navigation or additional network/action authority.

The command palette exposes **Kræver handling** only while the current Drift attention badge is non-zero. It routes to the same Live Activity surface. The palette now also consumes the same versioned structured HUD and Mission Control snapshots as the other global control-room layers: selected-person context comes from `personHud.dataset`, not the rendered person-name label, and **Næste handling** is present only when Mission Control reports a valid structured `attention` or `next` state with an allow-listed target tab. The palette revalidates that snapshot again when the command is executed, so a stale or malformed Mission target becomes a no-op instead of navigation authority. `unknown` and `complete` mission states expose no next-action command.

None of these control-room layers performs fetches, POSTs, shell execution, review approval or activation; the underlying typed Person Studio/Drift controls remain the only action authority.

