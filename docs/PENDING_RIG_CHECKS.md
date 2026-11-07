# Pending rig checks

Checks that can only be done on the physical rig, and that are still open. Every
entry says what to run, what to record and when it counts as passed. When a
check is done, fill in its **Result** block and move the entry to **Done**. The
open PR that adds an entry is the reminder: it is merged once the result is in.

## Open

### Local Stash staging: `-StageOnly` (BodyRig #1377)

**Why:** #1377 copies the selected Stash originals into a local snapshot first,
and then processes offline. Everything that changed can be checked in minutes.
A full clone, which takes days, is **not** needed.

**Before:** #1377 is merged, or its branch `feature/stash-local-source-snapshot-20261027`
is checked out. Stash and the media share are reachable.

**Run** (the same arguments as a normal clone, plus `-StageOnly`):

```powershell
.\clone-body-from-stash.ps1 -PerformerId <id> -ExternalPython "C:\...\recovery\python.exe" -FourDHumansRepo "C:\...\4D-Humans" -BodyId "check" -StageOnly
```

**Passed when all of these hold:**

- [ ] The run ends with `StageOnly: Stash selection and local staging verified`, and the exit code is 0.
- [ ] `Temporary local Stash source snapshot deleted.` is printed, and `<OutputDir>\local-source-snapshot` no longer exists.
- [ ] `<OutputDir>\bodyrig-staging-timing.json` exists, with `staged: true`, `stage_only: true`, plus `files`, `bytes`, `copy_seconds` and `verify_seconds`.
- [ ] The originals in Stash and on the share are unchanged.
- [ ] After the run, `$env:BODYRIG_STASH_OFFLINE` is empty and the Stash API key variable is back in the same PowerShell session.

**Result** (to be filled in):

| Field | Value |
| --- | --- |
| Date, rig | |
| BodyRig commit | |
| `files` / `bytes` | |
| `copy_seconds` / `verify_seconds` | |
| Observations | |

## Done

None yet.
