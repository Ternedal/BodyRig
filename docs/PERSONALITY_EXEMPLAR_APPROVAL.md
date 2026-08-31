# BodyRig transcript exemplar approval

Transcript extractorens output er kun forslag. Dette lag er den eksplicitte menneskelige gate mellem en `bodyrig-personality-exemplar-candidates` rapport og et Personality Blueprint.

## Authority chain

```text
TXT / SRT / VTT
  -> bodyrig-personality-exemplars
  -> kandidatrapport (ingen speaker/personality authority)
  -> menneske vælger konkrete candidate indexes
  -> bekræft speaker identity
  -> godkend style-only brug
  -> bodyrig-personality-approve-exemplars
  -> create-only approval receipt
  -> bodyrig-personality-blueprint --style-report ... --style-approval ...
  -> personality-rXXXX candidate
  -> ModelRig + VoiceRig audition
  -> human compatibility review
  -> Person Revision
```

Ingen af transcript-lagene giver authority til biografi, minder, holdninger eller indre mentale egenskaber. De godkendte replikker må kun påvirke sproglig stil: ordvalg, rytme, tone og conversational texture.

## Approval receipt

En approval receipt indeholder:

- SHA-256 af den canonical kandidatrapport,
- de valgte zero-based candidate indexes,
- de konkrete godkendte replikker,
- `speaker_identity_confirmed=true`,
- `style_use_approved=true`,
- `personality_authority=false`,
- `content_semantics=style-only-not-biography-or-memory`.

Receipt-validering alene er ikke nok. BodyRig verifierer altid receipt **mod den konkrete kandidatrapport**:

1. report SHA skal matche,
2. hvert index skal eksistere i den rapport,
3. teksten i receipt skal være præcis teksten på det index.

Ændres transcript-kandidatrapporten eller receiptens indexes/tekst efter godkendelsen, fejler verification closed.

## CLI

Først udtrækkes kandidater:

```powershell
bodyrig-personality-exemplars `
  .\transcripts\clip-01.srt `
  .\transcripts\interview.txt `
  --out "$env:LOCALAPPDATA\BodyRig\personality-exemplars\review-01.json"
```

Gennemgå `candidates` i rapporten. Når candidate index 0, 4 og 9 er verificeret som den rigtige person og ønskes som stilreferencer:

```powershell
bodyrig-personality-approve-exemplars `
  "$env:LOCALAPPDATA\BodyRig\personality-exemplars\review-01.json" `
  --index 0 `
  --index 4 `
  --index 9 `
  --confirm-speaker-identity `
  --approve-style-use `
  --out "$env:LOCALAPPDATA\BodyRig\personality-exemplars\approval-01.json"
```

Begge confirmation flags er obligatoriske. Approval-output er create-only.

## Brug i Personality Blueprint

```powershell
bodyrig-personality-blueprint `
  --person-id person-0123456789abcdef0123456789abcdef `
  --body-revision body-r0003 `
  --directness 0.75 `
  --warmth 0.70 `
  --playfulness 0.65 `
  --formality 0.25 `
  --verbosity 0.35 `
  --initiative 0.65 `
  --style-report "$env:LOCALAPPDATA\BodyRig\personality-exemplars\review-01.json" `
  --style-approval "$env:LOCALAPPDATA\BodyRig\personality-exemplars\approval-01.json" `
  --save-candidate `
  --out "$env:LOCALAPPDATA\BodyRig\personality-blueprints\candidate-01.json"
```

`--style-report` og `--style-approval` skal altid gives sammen. BodyRig verifierer bindingen før blueprintet bygges.

Den kompilerede personality candidates `style_notes` får:

- `style_report_sha256=<...>`
- `style_approval_sha256=<...>`

Person Assembly-fingerprintet inkluderer allerede personality `style_notes`. Derfor bliver en senere auditioneret og godkendt Person Revision transitivt bundet til den præcise transcript-review/approval evidence uden en Person Profile-schemaændring.

## Direkte authored style examples

`--style-example` eksisterer fortsat til replikker, som operatøren selv authorer direkte. Transcript extractor-output skal derimod gå gennem approval receipt, hvis BodyRig skal kunne dokumentere transcript provenance.

Det samlede antal style-exemplars er fortsat højst 12.
