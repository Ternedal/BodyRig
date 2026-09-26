from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
JS = (ROOT / "bodyrig" / "ui" / "person_command_palette.js").read_text(encoding="utf-8")
CSS = (ROOT / "bodyrig" / "ui" / "person_command_palette.css").read_text(encoding="utf-8")


def test_person_studio_has_command_palette() -> None:
    for token in (
        'id="personCommandPalette"',
        'id="personCommandPaletteBackdrop"',
        'id="personCommandPaletteInput"',
        'id="personCommandPaletteResults"',
    ):
        assert token in HTML
    assert '<script src="/ui/person_command_palette.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/person_command_palette.css">' in HTML


def test_command_palette_routes_to_existing_ui_only() -> None:
    for token in (
        '"overview"',
        '"body"',
        '"voice"',
        '"personality"',
        '"assemble"',
        '"history"',
        '"operations"',
        "personActivityToggle",
        "newPersonButton",
    ):
        assert token in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
    assert "/action" not in JS


def test_command_palette_has_keyboard_navigation() -> None:
    for token in ('key.toLowerCase() === "k"', '"ArrowDown"', '"ArrowUp"', '"Enter"', '"Escape"', '"Tab"'):
        assert token in JS
    assert "role=\"dialog\"" in HTML
    assert "aria-modal=\"true\"" in HTML
    assert "backdrop-filter:blur" in CSS


def test_command_palette_traps_and_restores_focus() -> None:
    for token in (
        "let previouslyFocused = null",
        "function paletteFocusable()",
        "function trapPaletteFocus(event)",
        'event.key !== "Tab"',
        "previouslyFocused = active instanceof HTMLElement ? active : null",
        "restore?.isConnected",
        "setTimeout(() => restore.focus(), 0)",
        'closePalette({ restoreFocus: false })',
        'function closePalette({ restoreFocus = true } = {})',
    ):
        assert token in JS

    assert 'role="combobox"' in HTML
    assert 'aria-autocomplete="list"' in HTML
    assert 'aria-controls="personCommandPaletteResults"' in HTML
    assert 'aria-expanded="false"' in HTML
    assert 'input.setAttribute("aria-expanded", "true")' in JS
    assert 'input?.setAttribute("aria-expanded", "false")' in JS
    assert "aria-activedescendant" in JS
    assert "personCommandOption-" in JS
    assert ":focus-visible" in CSS


def test_command_palette_exposes_attention_only_when_current_attention_exists() -> None:
    assert 'id: "attention"' in JS
    assert 'label: "Kræver handling"' in JS
    assert "when: () => attentionCount() > 0" in JS
    assert "availableCommands()" in JS
    assert "commandHint(command)" in JS
    assert "operatorAttentionBadge" in JS
    assert "MutationObserver" in JS
    assert "personActivityToggle" in JS
    assert "fetch(" not in JS
    assert "POST" not in JS


def test_command_palette_consumes_structured_person_and_mission_state() -> None:
    for token in (
        "structuredPersonContext",
        "structuredMissionState",
        'hud.dataset.stateVersion !== "1"',
        'root.dataset.stateVersion !== "1"',
        'new Set(["bound", "unbound", "unknown"])',
        'new Set(["unknown", "attention", "next", "complete"])',
        '"overview", "body", "voice", "personality", "assemble", "history", "operations"',
        "integerDataset",
        "missionActionAvailable",
        "runMissionAction",
        "personContextText",
    ):
        assert token in JS

    assert '$("personName")' not in JS
    assert "personMissionAction" not in JS
    assert 'when: () => missionActionAvailable()' in JS
    assert 'run: () => runMissionAction()' in JS
    assert "openTab(state.targetTab)" in JS
    assert 'return "Ingen verificeret person valgt."' in JS
    assert 'return "Ingen verificeret næste handling"' in JS


def test_command_palette_revalidates_structured_state_while_open() -> None:
    assert 'const personHud = $("personHud")' in JS
    assert 'const missionControl = $("personMissionControl")' in JS
    assert "new MutationObserver(refreshOpenPalette)" in JS
    assert '"data-person-name"' in JS
    assert '"data-person-revision"' in JS
    assert '"data-mission-kind"' in JS
    assert '"data-mission-target-tab"' in JS
    assert "detail.slice(0, 217)" in JS
    assert "fetch(" not in JS
    assert "POST" not in JS
