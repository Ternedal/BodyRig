# BodyRig Python dependency authority

BodyRig deliberately separates package compatibility from exact execution authority.

- `pyproject.toml` keeps normal runtime/test compatibility ranges broad enough for package and development use. The NumPy test dependency is interpreter-marked so Python 3.11/3.12 use NumPy 1.x compatibility while Python 3.13+ can resolve a supported NumPy 2.x release.
- `requirements/windows-python.lock.txt` is the exact CPython 3.11 Windows rig/operator/test runtime dependency set used by the canonical physical path.
- `requirements/linux-ci-python.lock.txt` is the exact Ubuntu CI dependency set used by the Python 3.11/3.12 software gates.
- platform-only dependencies stay platform-local (`colorama` on Windows, `uvloop` on Linux); common dependencies must use the same exact versions in both locks.
- the build backend is pinned separately in `pyproject.toml` so editable/wheel builds do not silently switch Hatchling versions.
- GitHub-hosted CI pins the major OS generation explicitly (`ubuntu-24.04` and `windows-2025`) instead of using `*-latest`, so a future major runner migration cannot silently change the execution platform for the same BodyRig revision.

The Windows runtime lock is revalidated at point of use by `bodyrig.runtime_lock`. Linux CI installs from its own exact constraints and verifies every listed distribution plus `pip check` before testing. Both exact execution locks intentionally retain `numpy==1.26.4`; the broader Python 3.13+ package/development marker does not change physical-rig or CI execution authority.

## Windows update fast path

`update-windows.ps1` does not need to reinstall an unchanged editable package on every source-only Git update. After checking out the exact target revision, current revisions first run two read-only probes against the repo-local `.venv`:

1. `python -m bodyrig.runtime_lock --lock requirements/windows-python.lock.txt` proves Python 3.11 plus every exact dependency version in the canonical Windows lock.
2. `python -m bodyrig.install_authority --repo-root <checkout>` proves the interpreter and `bodyrig.exe` are the checkout-local `.venv` artifacts, the installed BodyRig distribution is a PEP 610 editable install whose source URL resolves to this exact checkout, and the installed `bodyrig` console-script entry point is the expected `bodyrig.guided_app:run` target.

Only when **both** probes pass may the updater skip `pip install -e ".[test]"`. Any dependency mismatch, missing/stale launcher, non-editable install, different editable source checkout, stale console entry point, or probe failure falls back to the canonical locked pip install. After either path, the updater always runs the runtime-lock check again and, when the target revision contains the install-authority probe, always revalidates editable-install authority before Stash configuration/service launch.

Historical evidence revisions are intentionally backward-compatible. `bodyrig/install_authority.py` is not a required historical-target file: a safe ancestor revision that predates this probe uses the conservative locked pip-install path and then that revision's own `start-windows.ps1` checkout-import/launcher verification. New optimization tooling therefore cannot make older valid evidence unrecoverable.

The hosted-runner labels pin the OS generation, not GitHub's underlying weekly image build. That remaining image maintenance is outside repository control; BodyRig's exact package locks and exact-head checkout assertions continue to bind the Python and source layers inside that OS generation.

Changing either dependency lock or a pinned runner OS generation is a software-authority change and requires exact-head CI. Changing the verify/install decision logic is likewise operator-runtime authority and requires exact-head CI. None of these software checks creates or rebinds physical/human evidence.
