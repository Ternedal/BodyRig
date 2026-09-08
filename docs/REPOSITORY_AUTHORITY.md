# Repository authority

BodyRig's normal software/run authority is exact clean current `main`. That authority must be enforced by GitHub repository settings, not only by operator convention.

Issue #138 remains open until GitHub actually protects `main` with the required exact-green merge boundary.

## Canonical read-only verifier

After the repository setting has been applied by an authorized administrator, verify it from an exact clean `main` checkout:

```powershell
cd C:\Users\admin\Desktop\BodyRig-git
git fetch origin
git switch main
git pull --ff-only origin main
git status --short

.\verify-repository-authority.ps1
```

Machine-readable form:

```powershell
.\verify-repository-authority.ps1 -Json
```

The wrapper requires PowerShell 7+, an authenticated GitHub CLI (`gh`), exact clean local `main`, and GitHub `main` at the same Git revision as the checkout. It imports `bodyrig.repository_authority` from the same checkout and reads repository settings through GitHub's API without mutating them.

Until protection is configured, **FAIL is the expected result**. Do not reinterpret a failed verifier as a software or physical PASS.

## Accepted repository enforcement

The verifier accepts either classic branch protection or an equivalent active repository ruleset applying to `main`.

The effective policy must require all of the following status checks:

- `test (3.11)`;
- `test (3.12)`;
- `test-windows-python`;
- `acceptance-windows`;
- `adapter-log-handle`.

It must also:

- require a pull request before merge;
- require review-conversation/thread resolution;
- prevent force/non-fast-forward pushes;
- prevent deletion of `main`;
- prevent administrators/bypass actors from bypassing the verified repository boundary.

Requiring the branch to be up to date before merge is strongly recommended. The verifier reports this as a warning rather than a hard failure because BodyRig also uses deliberate exact-head/frozen-evidence workflows.

## Classic branch protection

A passing classic policy requires:

- `required_pull_request_reviews` present;
- `required_pull_request_reviews.bypass_pull_request_allowances` empty for users, teams and apps;
- all five required status checks;
- `enforce_admins.enabled=true`;
- `allow_force_pushes.enabled=false`;
- `allow_deletions.enabled=false`;
- `required_conversation_resolution.enabled=true`.

GitHub can explicitly allow selected users, teams, or apps to bypass required pull requests. Those `bypass_pull_request_allowances` are treated as a hard failure even when `enforce_admins` is enabled, because a named bypass actor would still make the exact-green PR boundary non-authoritative.

## Repository ruleset

A passing ruleset path requires one or more active branch rulesets whose combined effective rules on `main` include:

- `pull_request`, with `required_review_thread_resolution=true`;
- `required_status_checks`, containing all five exact contexts;
- `non_fast_forward`;
- `deletion`.

Applicable rulesets must not expose bypass actors. Rules that do not actually target `main`, disabled/evaluate-only rulesets, or incomplete status-check lists do not satisfy authority.

## Boundary

`verify-repository-authority.ps1` is read-only repository-settings evidence. It does not create or imply physical acceptance, human review, candidate promotion, or production activation.

Protecting `main` also does not retroactively alter historical evidence: existing evidence remains bound to the exact revisions and bytes it recorded.
