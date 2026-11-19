# BodyRig Photoreal V2 — næste verificerbare operatorforløb

_Oprettet 2026-10-08. Dette er en operator-guide, ikke acceptance-evidence._

## Autoritativt udgangspunkt

- **Software:** `main` dokumenterer P0 → P1 → P2 → P3 og M4 → M6 samt en særskilt fysisk Windows/Quest-acceptance.
- **Faktisk menneske-/hardwarestatus:** Kan ikke udledes af en grøn GitHub-test eller ældre loglinjer. Brug kun friske lokale, hash-bundne receipts og eksplicit human review.
- **Performer 42:** [#817](https://github.com/Ternedal/BodyRig/issues/817) kræver et troværdigt statisk ExAvatar-teacher-resultat vurderet mod held-out referencer, inden P2/P3 kan kvalificeres.
- **Repository-policy:** [#138](https://github.com/Ternedal/BodyRig/issues/138) kræver live branch protection. Følg ikke en ny `main`-revision som “frossen V1” uden eksplicit re-freeze.

## Read-only først

På Windows, fra det **eksisterende** checkout (ændr ikke branches, hvis det indeholder lokale ændringer):

```powershell
git status --short
git rev-parse HEAD
.\bodyrig-status.ps1
```

Gem output lokalt. Hvis checkout er dirty, service-revision afviger eller status-checker returnerer BLOCKED/ERROR, er næste handling fejlsøgning — **ikke** en ny fysisk clone.

Hvis en fysisk Gate A allerede findes, så inspicér i stedet dens fulde fortsættelseskæde:

```powershell
.\physical-acceptance-status.ps1 -AcceptanceDir "C:\path\to\acceptance" -Json
```

Dette er kun gyldigt med et checkout-bundet BodyRig-Python-miljø. Brug statusværktøjets faktiske next-command, ikke en kommando konstrueret ud fra et gammelt logudsnit.

## P0 → P1 stop/go

1. Verificér source-inventory, lokale kildefiler og fingerprints; hold TRAIN og HELD-OUT adskilt.
2. Verificér ExAvatar-rig/WSL-readiness med projektets egne pinned preflight-værktøjer.
3. Gennemfør statisk teacher-rendering og sammenlign **held-out** front, 3/4, profil samt helfigur i de view-retninger, der har reel kildeevidens.
4. Menneskelig reviewer skal eksplicit afvise mannequin/wax look, generiske øjne/hår, identity drift, defekte hænder og view collapse.
5. Uden et faktisk review-PASS: **STOP**. Et ExAvatar-checkpoint, en færdig træning eller et succesfuldt PowerShell-exit er ikke et visuelt PASS.

## P2-animation: næste trin *efter* accepteret P1

Se [P2 animation input](PHOTOREAL_V2_P2_EXAVATAR_ANIMATION_INPUT.md) og [P2 runner](PHOTOREAL_V2_P2_EXAVATAR_ANIMATION_RUNNER.md). Brug kun godkendt teacher-checkpoint, fire identitetsfiler og verificeret TRAIN motion-driver. Den dokumenterede launcher er:

```powershell
.\run-photoreal-v2-p2-exavatar-animation.ps1 -TeacherWorkRoot "C:\path\to\teacher-work"
```

Validér `animation-execution-receipt.json`, `review/animation.mp4` og hash-bindinger. Execution-receipt beviser ikke visual fidelity. Human animated review er separat obligatorisk. HELD-OUT motion må ikke røbes til inference-trinnet.

## Kun efter P1/P2 human PASS

P3-distillation og efterfølgende Windows/Quest-prober må først kvalificeres via deres eksisterende kontrakter. Hver platform skal vise samme accepterede package/runtime og samme faste deformation-sweep; menneskelig visuel attestation er stadig et selvstændigt gate. `production_activation=true` må alene komme fra den endelige validerede release, aldrig fra dette dokument eller fra en CI-test.

## Rapportér status uden at opfinde resultater

| Gate | Evidens der skal vedlægges | Hvis den mangler |
| --- | --- | --- |
| Repository authority | Live `verify-repository-authority.ps1` PASS | BLOCKED |
| P0 source/split | P0-receipts og source-hashes | BLOCKED |
| P1 static teacher | Held-out render-compare + eksplicit human review | BLOCKED |
| P2 animation | Hash-bundet execution receipt + human animated review | BLOCKED |
| P3 device fidelity | P3-evidence + human/device-review | BLOCKED |
| Physical Windows/Quest | Canonical machine/deformation evidence + human attestations | BLOCKED |
| M6 full digital twin | Valideret Person Revision og endelig release-receipt | BLOCKED |

**Prioritet:** Få ægte P1 visual-acceptance for performer 42, før mere animations- eller device-kode igangsættes.