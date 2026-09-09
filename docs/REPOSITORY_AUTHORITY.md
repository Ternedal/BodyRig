# Repository authority

BodyRig's normal software/run authority is exact clean current `main`. That authority must be enforced by GitHub repository settings, not only by operator convention.

Issue #138 remains open until GitHub actually protects `main` with the required exact-green merge boundary.

## Why up-to-date branch enforcement is mandatory

On 9 September 2026, PR #252 was fully qualified on its exact head while another PR (#253) advanced `main` immediately before #252 was squash-merged. The resulting combined tree was requalified successfully after merge, but the race demonstrated that exact-head CI alone does not prove the tree that will land when `main` is allowed to move concurrently.

Therefore repository authority requires GitHub's up-to-date-branch policy (`strict=true` for classic protection or `strict_required_status_checks_policy=true` for rulesets). A stale PR is a repository-authority failure, not a warning. This merge rule does not invalidate frozen physical-evidence workflows; it only governs whether a PR may update `main`.

## Canonical admin helper

For this repository's current personal-repository layout, `configure-repository-authority.ps1` can apply the accepted **classic branch protection** policy using an authenticated GitHub CLI identity with repository `Administration: write`.

Start from exact clean current `main` and inspect the intended payload without mutating GitHub:

```powershell
cd C:\Users\admin\Desktop\BodyRig-git
git fetch origin
git switch main
git pull --ff-only origin main
git status --short

.\configure-repository-authority.ps1
```

The default invocation is a dry run. It proves local `main` equals GitHub `main`, confirms no repository rulesets are present, refuses to replace existing classic branch protection, and prints the exact policy it would submit.

To apply that policy explicitly:

```powershell
.\configure-repository-authority.ps1 -Apply
```

The helper configures the exact six required checks with `app_id=15368`, `strict=true`, admin enforcement, required pull-request flow, `required_approving_review_count=0`, required conversation resolution, force-push blocking, and branch-deletion blocking. Zero required approving reviews is deliberate for the current solo repository: a pull request is still mandatory, while the repository is not made impossible to merge without another reviewer.

The helper refuses to compose over existing repository rulesets because combining unknown rules with a new classic rule is not safe automation. If classic branch protection already exists, it also refuses replacement unless the administrator deliberately uses:

```powershell
.\configure-repository-authority.ps1 -Apply -ReplaceExistingProtection
```

That override replaces the classic protection payload and should only be used after reviewing the live protection state. The helper never removes protection automatically if post-write verification fails; it leaves the repository fail-closed for inspection.

After a successful write, the helper automatically runs the checkout-bound `verify-repository-authority.ps1`. A successful API write without a verifier PASS is **not** repository authority.

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
- `adapter-log-handle`;
- `analyze (python)`.

All six checks must also be source-bound to the GitHub Actions GitHub App, app/integration ID `15368`. A matching context name alone is not sufficient repository authority: GitHub allows required status checks to be restricted to a specific GitHub App, and BodyRig deliberately requires that stronger binding so another integration cannot satisfy the exact-green boundary merely by emitting the same context name.

`analyze (python)` is the stable check name emitted by BodyRig's pinned `.github/workflows/codeql.yml`. It is a GitHub Actions check from app ID `15368`; the separate GitHub Advanced Security bot/summary surface is not a substitute for this exact check.

The effective policy must also:

- require a pull request before merge;
- require the branch to be up to date before merge;
- require review-conversation/thread resolution;
- prevent force/non-fast-forward pushes;
- prevent deletion of `main`;
- prevent administrators/bypass actors from bypassing the verified repository boundary.

## Classic branch protection

A passing classic policy requires:

- `required_pull_request_reviews` present;
- `required_pull_request_reviews.bypass_pull_request_allowances` empty for users, teams and apps;
- all six required status checks;
- every required check present in `required_status_checks.checks` with `app_id=15368`;
- `required_status_checks.strict=true`;
- `enforce_admins.enabled=true`;
- `allow_force_pushes.enabled=false`;
- `allow_deletions.enabled=false`;
- `required_conversation_resolution.enabled=true`.

GitHub can explicitly allow selected users, teams, or apps to bypass required pull requests. Those `bypass_pull_request_allowances` are treated as a hard failure even when `enforce_admins` is enabled, because a named bypass actor would still make the exact-green PR boundary non-authoritative.

GitHub's classic protection API also exposes each required check as a `checks` entry with an optional `app_id`. BodyRig requires `app_id=15368` for every one of the six required contexts. A contexts-only configuration, `app_id=-1`, `app_id=null`, or another app ID fails closed because the verifier cannot prove the check is restricted to GitHub Actions.

## Repository ruleset

A passing ruleset path requires one or more active branch rulesets whose combined effective rules on `main` include:

- `pull_request`, with `required_review_thread_resolution=true`;
- `required_status_checks`, containing all six exact contexts and `strict_required_status_checks_policy=true`;
- every required status-check entry with `integration_id=15368`;
- `non_fast_forward`;
- `deletion`.

Applicable rulesets must not expose bypass actors. Rules that do not actually target `main`, disabled/evaluate-only rulesets, incomplete status-check lists, stale-branch-permitting status policy, or required checks not bound to GitHub Actions integration ID `15368` do not satisfy authority.

## Boundary

`verify-repository-authority.ps1` remains read-only repository-settings evidence. `configure-repository-authority.ps1` is an explicit administrator mutation helper whose only authority is repository configuration. Repository-authority tooling does not create or imply physical acceptance, human review, candidate promotion, or production activation.

Protecting `main` also does not retroactively alter historical evidence: existing evidence remains bound to the exact revisions and bytes it recorded.
