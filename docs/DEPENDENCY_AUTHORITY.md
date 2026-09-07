# BodyRig Python dependency authority

BodyRig deliberately separates package compatibility from exact execution authority.

- `pyproject.toml` keeps normal runtime/test compatibility ranges broad enough for package and development use.
- `requirements/windows-python.lock.txt` is the exact CPython 3.11 Windows rig/operator/test runtime used by the canonical physical path.
- `requirements/linux-ci-python.lock.txt` is the exact Ubuntu CI dependency set used by the Python 3.11/3.12 software gates.
- platform-only dependencies stay platform-local (`colorama` on Windows, `uvloop` on Linux); common dependencies must use the same exact versions in both locks.
- the build backend is pinned separately in `pyproject.toml` so editable/wheel builds do not silently switch Hatchling versions.

The Windows runtime lock is revalidated at point of use by `bodyrig.runtime_lock`. Linux CI installs from its own exact constraints and verifies every listed distribution plus `pip check` before testing.

Changing either lock is a software-authority change and requires exact-head CI. It does not create or rebind physical/human evidence.
