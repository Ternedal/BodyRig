# Photoreal digital-twin operator status

The Photoreal software authority chain is additive:

```text
accepted P3
  -> Photoreal Person binding
  -> M4 Photoreal link
  -> canonical M5 Windows + Quest
  -> Photoreal M5 link
  -> canonical M6
  -> final Photoreal M6 release
```

Each authority already has a strict create-only writer and strict readback. This status layer does **not** create or alter any of them. It composes their current state and returns the exact next safe operator command.

## Run

```powershell
.\photoreal-digital-twin-status.ps1 `
  -CompositionAuthorityDir <M4_AUTHORITY_DIR> `
  -AcceptanceDir <CANONICAL_ACCEPTANCE_DIR> `
  -PhotorealPersonBinding <PHOTOREAL_PERSON_BINDING_JSON> `
  -P3PhysicalReview <P3_PHYSICAL_RUNTIME_REVIEW_JSON>
```

Use `-LibraryRoot` only when the canonical Person library is intentionally overridden.

The PowerShell wrapper is read-only. It points Python at the exact local checkout and passes that checkout as the only source allowed to authorize an executable next command.

## State machine

The inspector strict-validates the canonical digital-twin chain first. Invalid or blocked canonical evidence fails closed and suppresses Photoreal commands.

When canonical evidence is safe, the next gate is selected in this order:

1. `photoreal_m4_link` — create/revalidate the exact M4 ↔ accepted-P3 authority;
2. canonical M5 — complete real WindowsPlayer and Quest-class realizations when still missing;
3. `photoreal_m5_link` — bind those exact canonical realization bytes to Photoreal authority;
4. canonical M6 — finalize the base activating digital-twin release when still missing;
5. `photoreal_m6_release` — bind exact canonical M6 + Photoreal M5 into final Photoreal production authority;
6. `complete` — only after final Photoreal M6 strict-readback passes.

A required action is executable only when the operator checkout:

- exists and contains all required Photoreal scripts;
- has the exact BodyRig revision bound by the M4/Photoreal evidence;
- is clean.

Otherwise the state becomes `operator-checkout` blocked or inspection-only with no executable command.

## Completion rule

The operator may report:

```text
state = complete
photoreal_digital_twin_ready = true
production_activation = true
```

only after `read_photoreal_release()` strict-revalidates the expected final release against live canonical M6, Photoreal M5, M4 and platform evidence.

Canonical M6 readiness alone is therefore not enough for the Photoreal status to claim completion.
