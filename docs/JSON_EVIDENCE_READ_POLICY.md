# JSON evidence read policy

**Status:** decided 2026-11-07 (Anders, delegated to Claude: "fix det sidste"; #1386 recommendation B, slice 3).
**Scope:** every module-private `_read_json`/`_load_json` helper that reads a receipt, evidence or
authority file and fails closed with its module's own error class.

## Decision

All such helpers delegate to `bodyrig.json_io.read_json_object(path, *, error, unreadable, not_object)`,
which implements one canonical behaviour:

| Knob | Canonical behaviour | Historical spread (140 helpers) | Why |
| --- | --- | --- | --- |
| Encoding | UTF-8 with optional BOM (`utf-8-sig`) | 123 `utf-8-sig`, 16 `utf-8`, 1 other | Windows tooling (PowerShell 5.1 `Set-Content -Encoding UTF8`) emits BOMs. The bytes after the BOM are the same document; rejecting it is a spurious fail-closed, not a safety property. |
| `NaN` / `Infinity` tokens | Rejected (`parse_constant` raises) | 57 rejected, 83 accepted | No BodyRig writer emits them — every canonical dump uses `allow_nan=False` — so they only ever mean a malformed or foreign file. Rejecting at read time is fail-closed one layer earlier than the per-field checks that used to catch them. |
| Top-level value | Must be a JSON object | 139 required, 1 did not | Every receipt/evidence format is an object with `format`/`version`. |
| Failures turned into the module error | `OSError`, `UnicodeError`, `ValueError` (covers `json.JSONDecodeError`) | `UnicodeDecodeError` vs `UnicodeError`, with/without `ValueError` | Superset of every historical tuple; a failure that previously escaped as a raw exception now fails closed with the module's message. |
| Error class and messages | The caller's, unchanged | per module | The module's fail-closed wording is part of its contract and its tests. |
| Pre-checks (`is_file()`, `is_symlink()`) and `Path(...).expanduser().resolve()` | Stay in the calling module | 23 pre-checks, 51 resolve | They carry their own messages and belong to the module's authority logic, not to parsing. |

## Consequences

- 131 helpers now share one implementation (`bodyrig/json_io.py`); the nine helpers whose shape differs
  (extra validation inside the `try`, list documents, non-object returns) are listed in
  `tests/test_json_io_shared_contract.py::KEPT` and re-reviewed when their module changes.
- Observable behaviour changes, all in the fail-closed direction or neutral:
  - 16 modules now accept a BOM-prefixed file they previously rejected (neutral: same document);
  - 83 modules now reject `NaN`/`Infinity` tokens at read time with their *unreadable* message instead of
    accepting the value and (where they had one) rejecting it later with a field-level message. One test
    pinned the later message (`test_high_fidelity_hair_deformation_numeric_boundaries.py`) and was updated
    to expect the reader's message for those tokens;
  - every migrated module chains the cause (`raise error(...) from exc`), which some did not.
- No hash, receipt format, evidence binding or `production_activation` semantics change.
- The contract test forbids the `json.loads(<path>.read_text(...))` core from reappearing in a
  `_read_json`-style helper outside `json_io.py`, so the class stays closed.

## Not covered (deliberately)

- Modules without any `bodyrig` import keep their own copies: they run standalone inside external
  environments (SiTH/ExAvatar bridges, WSL-side scripts) where `bodyrig` is not importable.
- `_sha`/`_canonical_sha` validators (95 helpers, 25 shapes) are **not** unified by this decision. Their
  spread is semantic — whether input is lower-cased before the 64-hex check, regex vs manual check,
  `_text(maximum=64)` type gating — and PowerShell's `Get-FileHash` emits upper-case hex, so a strict
  lowercase-only policy could fail a legitimate rig path at runtime. Any unification there is a separate
  decision with its own rig evidence.
