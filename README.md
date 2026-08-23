# BodyRig

BodyRig giver ModelRig en visuel og kropslig tilstedeværelse.

- **ModelRig** tænker og producerer semantisk intent.
- **VoiceRig** lytter og taler.
- **BodyRig** bygger en portabel kropsprofil fra video og omsætter intent + taletiming til ansigt/kropsadfærd.
- **Kaliv / VR-klienter** renderer avataren.

## V1-mål

Det normale flow skal være:

> vælg 1–10 videoklip → identificér personen → udled bodyprint → byg/fit avatar → eksportér `.mrbody` → brug samme profil i Windows/Android/Quest-klienter.

V1 er local-first. Kildevideo er build-input og må ikke ende i den portable profil eller support-output.

## Kør bootstrap

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[test]"
pytest -q
bodyrig
```

BodyRig kører som standard på `127.0.0.1:8775`.

## Arkitektur

```text
ModelRig -- BodyCue ------------------+
                                      v
                                  BodyRig ----> renderer/Kaliv/VR
                                      ^
VoiceRig -- utterance/viseme timing --+

video --> recovery-engine (isolated) --> canonical 3D joints/tracks
      --> BodyRig bodyprint extractor --> avatar fitting/VRM --> .mrbody
```

Recovery-motorer holdes bag en procesgrænse, så research-stack, checkpoints og kropsmodel-licenser ikke bliver skjulte runtime-afhængigheder.

Se `docs/ARCHITECTURE.md` og `docs/MRBODY_SPEC.md`.
