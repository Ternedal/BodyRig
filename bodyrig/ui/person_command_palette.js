(() => {
  const $ = (id) => document.getElementById(id);
  let open = false;
  let activeIndex = 0;
  const COMPONENT_STATES = new Set(["bound", "unbound", "unknown"]);
  const MISSION_KINDS = new Set(["unknown", "attention", "next", "complete"]);
  const TARGET_TABS = new Set(["overview", "body", "voice", "personality", "assemble", "history", "operations"]);

  const commands = [
    { id: "overview", label: "Overblik", hint: "Person pipeline og samlet status", keywords: "overview overblik pipeline person", run: () => openTab("overview") },
    { id: "body", label: "Krop", hint: "Body-kandidater, Photoreal og ExAvatar", keywords: "krop body photoreal exavatar", run: () => openTab("body") },
    { id: "voice", label: "Stemme", hint: "VoiceRig-kandidater", keywords: "stemme voice voicerig", run: () => openTab("voice") },
    { id: "personality", label: "Personality Lab", hint: "Guided Personality og audition suite", keywords: "personality personlighed guided audition lab", run: () => openTab("personality") },
    { id: "assemble", label: "Saml person", hint: "Canonical audition og compatibility review", keywords: "assemble saml person audition compatibility review", run: () => openTab("assemble") },
    { id: "history", label: "Historik", hint: "Revisioner og tidligere kandidater", keywords: "historik history revisioner", run: () => openTab("history") },
    { id: "operations", label: "Drift", hint: "Services, jobs, launches og Digital Twin", keywords: "drift operations jobs launches digital twin", run: () => openTab("operations") },
    { id: "attention", label: "Kræver handling", hint: () => `Åbn ${attentionCount()} prioriterede operator-punkt${attentionCount() === 1 ? "" : "er"}`, keywords: "attention handling blocker operator drift kræver", when: () => attentionCount() > 0, run: () => $("personActivityToggle")?.click() },
    { id: "activity", label: "Live Activity", hint: "Åbn global execution stream", keywords: "activity live execution stream jobs launches", run: () => $("personActivityToggle")?.click() },
    { id: "focus", label: "Focus Mode", hint: "Skjul sidebar og giv arbejdsfladen fuld bredde", keywords: "focus fokus fullscreen sidebar workspace", run: () => $("personFocusToggle")?.click() },
    { id: "mission", label: "Næste handling", hint: () => missionHint(), keywords: "mission next næste action blocker priority", when: () => missionActionAvailable(), run: () => runMissionAction() },
    { id: "new-person", label: "Ny person", hint: "Opret ny BodyRig-person", keywords: "ny new person create opret", run: () => $("newPersonButton")?.click() },
  ];

  function integerDataset(root, key) {
    const raw = String(root?.dataset?.[key] || "").trim();
    if (!/^\d+$/.test(raw)) return null;
    const value = Number(raw);
    return Number.isSafeInteger(value) ? value : null;
  }

  function structuredPersonContext() {
    const hud = $("personHud");
    if (!hud || hud.dataset.stateVersion !== "1") return null;

    const name = String(hud.dataset.personName || "").trim();
    const revision = String(hud.dataset.personRevision || "").trim();
    const complete = integerDataset(hud, "pipelineComplete");
    const total = integerDataset(hud, "pipelineTotal");
    const body = String(hud.dataset.bodyState || "");
    const voice = String(hud.dataset.voiceState || "");
    const personality = String(hud.dataset.personalityState || "");

    if (
      name.length > 160
      || revision.length > 160
      || complete === null
      || total === null
      || complete > total
      || !COMPONENT_STATES.has(body)
      || !COMPONENT_STATES.has(voice)
      || !COMPONENT_STATES.has(personality)
    ) {
      return null;
    }
    return { name, revision, complete, total };
  }

  function structuredMissionState() {
    const root = $("personMissionControl");
    if (!root || root.dataset.stateVersion !== "1") return null;

    const kind = String(root.dataset.missionKind || "").trim();
    const title = String(root.dataset.missionTitle || "").trim();
    const detail = String(root.dataset.missionDetail || "").trim();
    const targetTab = String(root.dataset.missionTargetTab || "").trim();
    const actionLabel = String(root.dataset.missionActionLabel || "").trim();

    if (!MISSION_KINDS.has(kind) || !title || !detail) return null;
    if (title.length > 160 || detail.length > 1000 || actionLabel.length > 120) return null;
    if (targetTab && !TARGET_TABS.has(targetTab)) return null;
    if ((kind === "attention" || kind === "next") && !targetTab) return null;
    if ((kind === "unknown" || kind === "complete") && targetTab) return null;
    return { kind, title, detail, targetTab, actionLabel };
  }

  function missionActionAvailable() {
    const state = structuredMissionState();
    return Boolean(state && (state.kind === "attention" || state.kind === "next"));
  }

  function missionHint() {
    const state = structuredMissionState();
    if (!state || (state.kind !== "attention" && state.kind !== "next")) {
      return "Ingen verificeret næste handling";
    }
    return `${state.title} · ${state.detail}`;
  }

  function runMissionAction() {
    const state = structuredMissionState();
    if (!state || (state.kind !== "attention" && state.kind !== "next")) return;
    openTab(state.targetTab);
  }

  function personContextText() {
    const state = structuredPersonContext();
    if (!state || !state.name) return "Ingen verificeret person valgt.";
    return state.revision
      ? `Valgt person · ${state.name} · ${state.revision}`
      : `Valgt person · ${state.name} · ingen aktiv revision`;
  }

  function attentionCount() {
    const count = Number($("operatorAttentionBadge")?.dataset?.activeCount);
    return Number.isInteger(count) && count >= 0 ? count : 0;
  }

  function commandLabel(command) {
    return typeof command.label === "function" ? command.label() : String(command.label || "");
  }

  function commandHint(command) {
    return typeof command.hint === "function" ? command.hint() : String(command.hint || "");
  }

  function availableCommands() {
    return commands.filter((command) => typeof command.when !== "function" || command.when());
  }

  function openTab(tab) {
    document.querySelector(`.tab[data-tab="${tab}"]`)?.click();
  }

  function matches(command, query) {
    const haystack = `${commandLabel(command)} ${commandHint(command)} ${command.keywords}`.toLowerCase();
    return query.split(/\s+/).filter(Boolean).every((part) => haystack.includes(part));
  }

  function filtered() {
    const query = ($("personCommandPaletteInput")?.value || "").trim().toLowerCase();
    const available = availableCommands();
    return query ? available.filter((command) => matches(command, query)) : available;
  }

  function render() {
    const target = $("personCommandPaletteResults");
    if (!target) return;
    const items = filtered();
    if (activeIndex >= items.length) activeIndex = Math.max(0, items.length - 1);
    target.replaceChildren();

    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "person-command-empty";
      empty.textContent = "Ingen matchende handlinger.";
      target.appendChild(empty);
      return;
    }

    items.forEach((command, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `person-command-item${index === activeIndex ? " active" : ""}`;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", String(index === activeIndex));
      button.dataset.commandId = command.id;

      const copy = document.createElement("span");
      copy.className = "person-command-copy";
      const label = document.createElement("strong");
      label.textContent = commandLabel(command);
      const hint = document.createElement("span");
      hint.textContent = commandHint(command);
      copy.append(label, hint);

      const enter = document.createElement("span");
      enter.className = "person-command-enter";
      enter.textContent = "↵";
      button.append(copy, enter);

      button.addEventListener("mouseenter", () => {
        activeIndex = index;
        render();
      });
      button.addEventListener("click", () => execute(index));
      target.appendChild(button);
    });
  }

  function execute(index = activeIndex) {
    const items = filtered();
    const command = items[index];
    if (!command) return;
    closePalette();
    command.run();
  }

  function openPalette() {
    open = true;
    activeIndex = 0;
    $("personCommandPalette")?.classList.remove("hidden");
    $("personCommandPaletteBackdrop")?.classList.remove("hidden");
    $("personCommandPalette")?.setAttribute("aria-hidden", "false");
    $("personCommandPaletteBackdrop")?.setAttribute("aria-hidden", "false");
    document.body.classList.add("person-command-open");
    const context = $("personCommandPaletteContext");
    if (context) context.textContent = personContextText();
    const input = $("personCommandPaletteInput");
    if (input) {
      input.value = "";
      setTimeout(() => input.focus(), 0);
    }
    render();
  }

  function closePalette() {
    open = false;
    $("personCommandPalette")?.classList.add("hidden");
    $("personCommandPaletteBackdrop")?.classList.add("hidden");
    $("personCommandPalette")?.setAttribute("aria-hidden", "true");
    $("personCommandPaletteBackdrop")?.setAttribute("aria-hidden", "true");
    document.body.classList.remove("person-command-open");
  }

  $("personCommandPaletteInput")?.addEventListener("input", () => {
    activeIndex = 0;
    render();
  });
  $("personCommandPaletteBackdrop")?.addEventListener("click", closePalette);

  function refreshOpenPalette() {
    if (!open) return;
    const context = $("personCommandPaletteContext");
    if (context) context.textContent = personContextText();
    render();
  }

  const personHud = $("personHud");
  if (personHud) {
    new MutationObserver(refreshOpenPalette).observe(personHud, {
      attributes: true,
      attributeFilter: [
        "data-state-version",
        "data-person-name",
        "data-person-revision",
        "data-pipeline-complete",
        "data-pipeline-total",
        "data-body-state",
        "data-voice-state",
        "data-personality-state",
      ],
    });
  }

  const missionControl = $("personMissionControl");
  if (missionControl) {
    new MutationObserver(refreshOpenPalette).observe(missionControl, {
      attributes: true,
      attributeFilter: [
        "data-state-version",
        "data-mission-kind",
        "data-mission-title",
        "data-mission-detail",
        "data-mission-target-tab",
        "data-mission-action-label",
      ],
    });
  }

  const attentionBadge = $("operatorAttentionBadge");
  if (attentionBadge) {
    new MutationObserver(refreshOpenPalette).observe(attentionBadge, {
      attributes: true,
      attributeFilter: ["data-active-count", "data-unseen-count"],
    });
  }

  document.addEventListener("keydown", (event) => {
    const metaK = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k";
    if (metaK) {
      event.preventDefault();
      open ? closePalette() : openPalette();
      return;
    }
    if (!open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closePalette();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      const count = filtered().length;
      if (count) activeIndex = (activeIndex + 1) % count;
      render();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      const count = filtered().length;
      if (count) activeIndex = (activeIndex - 1 + count) % count;
      render();
    } else if (event.key === "Enter") {
      event.preventDefault();
      execute();
    }
  });
})();