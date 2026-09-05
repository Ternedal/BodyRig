# BodyRig high-fidelity integration handoff

Updated: 2026-09-05.

## Authority and branch

- Canonical software trunk remains `main`; last verified trunk SHA is
  `438201ddf8131e3de646b5057006463b64eadc86` (PR #72).
- This checkout continues the existing draft PR #83 on
  `agent/high-fidelity-integration-20260904`. It is an integration candidate,
  not replacement trunk authority.
- PR #83 is stacked on PR #54, exact base
  `a33372de359a24b3daffae4649a06008d00179bd`, because its Person Studio flow
  depends on the unmerged anatomy/hair/eyes/face-secondary component chain.
  No additional sibling branch was created.
- The starting integration head for this continuation was
  `da73358ceebd784042139a0edfb634e755f6df7f`, with CI #1624 and Windows
  log-handle regression #796 successful. Current head and its CI results are
  recorded on PR #83; do not reuse this starting SHA as current authority.
- Historical physical evidence keeps its recorded exact revision. Nothing in
  this continuation rebases, rewrites or replaces existing physical evidence.

## Completed in this continuation

- Final component status verifies the promoted package SHA before and after
  audit and checks the audit's own package SHA. A missing/replaced package
  cannot remain component-complete.
- Release readiness verifies the same package bytes before and after final
  human-review validation. A passing review records the package SHA in status
  and clears the outstanding human-review flag; physical/production gates stay
  required.
- Corrupt component reviews return a blocked status. Contradictory `state` and
  `passed` values cannot advance the flow. Existing runtime output with missing
  nested evidence is invalid, rather than an invitation to rerun a create-only
  operator into the same directory.
- Blocked stages expose their reason and suppress runnable next commands.
  Component/hair review templates name their real confirmation switches and
  still require the operator's assessment. PowerShell path values use literal
  quoting, including apostrophes, dollar signs and backticks.
- Person Studio resumes polling after an empty preview response, immediately
  clears the previous person's readiness on selection changes, ignores stale
  responses, and shows blocked review status ahead of package-complete badges.
  API labels and error messages are inserted as text rather than HTML.

## Verification

- Full local Python 3.12 suite: **1267 passed, 1 skipped**.
- The skip is the native PowerShell quoting test: local `pwsh` is unavailable;
  the canonical CI Python jobs provide PowerShell and execute that test.
- Node UI behaviour suite: **4 passed**, included in the Python suite through
  its subprocess runner. Uses Node built-ins; no new application dependency.
- Exact updated-head CI results belong in PR #83 after push.
- No target-rig CUDA/SiTH, real human visual review, WindowsPlayer or Quest
  physical acceptance was performed in this environment.

## Next concrete work

The unified continuation reaches a component-complete package and validates its
package-bound final human review. The next action still stops at
`physical_windows_acceptance` with no runnable command. Complete the explicit
handoff of that exact promoted package into the canonical physical acceptance
flow, then expose the validated Windows / Quest / final-release next step in
Person Studio. Do not point an old clone/package acceptance receipt at newly
promoted bytes, infer physical PASS from component review, or rerun retained
reconstruction merely to create new authority.

Keep PR #83 draft until the remaining operator/UI and final release-readiness
contract are complete. `production_ready=false` and `production_activation=false`
remain mandatory throughout this continuation. Human source-identity review,
real Windows/Quest acceptance and canonical final release remain separate gates.
