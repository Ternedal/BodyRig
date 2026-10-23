# Package and CLI audit — BodyRig

Source inspection: 2026-10-23; `pyproject.toml` on main. **No commands executed.**

- Package: `bodyrig` **0.1.0**, Python **>=3.11**, Hatchling **1.32.0**.
- Base dependencies include FastAPI >=0.115, Uvicorn >=0.30, Pydantic >=2.8 and Pillow >=10.
- Declared commands include `bodyrig`, `bodyrig-recover`, `bodyrig-recovery-preflight`, `bodyrig-capture-identity`, `bodyrig-fit-avatar`, `bodyrig-wsl-adapter-bridge`, and multiple `bodyrig-sith-*` and `bodyrig-photoreal-*` utilities. This list is not exhaustive; consult the project script table for the current exact set.
- The presence of a CLI entry point is **not** evidence that source reconstruction, physical identity acceptance or Unity/Quest rendering has passed.

## Operator checks

- [ ] Record exact SHA, Python environment and installed extras.
- [ ] Confirm all referenced CLI targets import and `--help` returns successfully.
- [ ] Check Windows/WSL paths, source permissions and external storage.
- [ ] Verify physical acceptance and exact-revision evidence separately from unit tests.

See [architecture](ARCHITECTURE.md) and [integration acceptance](INTEGRATION_ACCEPTANCE_2026-10-23.md).
