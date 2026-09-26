(() => {
  const $ = (id) => document.getElementById(id);
  let open = false;
  let activeIndex = 0;

  const commands = [
    { id: "overview", label: "Overblik", hint: "Person pipeline og samlet status", keywords: "overview overblik pipeline person", run: () => openTab("overview") },
    { id: "body", label: "Krop", hint: "Body-kandidater, Photoreal og ExAvatar", keywords: "krop body photoreal exavatar", run: () => openTab("body") },
    { id: "voice", label: "Stemme", hint: "VoiceRig-kandidater", keywords: "stemme voice voicerig", run: () => openTab("voice") },
    { id: "personality", label: "Personality Lab", hint: "Guided Personality og audition suite", keywords: "personality personlighed guided audition lab", run: () => openTab("personality") },
    { id: "assemble", label: "Saml person", hint: "Canonical audition og compatibility review", keywords: "assemble saml person audition compatibility review", run: () => openTab("assemble") },
    { id: "history", label: "Historik", hint: "Revisioner og tidligere kandidater", keywords: "historik history revisioner", run: () => openTab("history") },
    { id: "operations", label: "Drift", hint: "Services, jobs, launches og Digital Twin", keywords: "drift operations jobs launches digital twin", run: () => openTab("operations") },
    { id: "activity", label: "Live Activity", hint: "Åbn global execution stream", keywords: "activity live execution stream jobs launches", run: () => $("personActivityToggle")?.click() },
    { id: "focus", label: "Focus Mode", hint: "Skjul sidebar og giv arbejdsfladen fuld bredde", keywords: "focus fokus fullscreen sidebar workspace", run: () => $("personFocusToggle")?.click() },
    { id: "new-person", label: "Ny person", hint: "Opret ny BodyRig-person", keywords: "ny new person create opret", run: () => $("newPersonButton")?.click() },
  ];

  function selectedPerson() {
    return ($("personName")?.textContent || "").trim();
  }

  function openTab(tab) {
    document.querySelector(`.tab[data-tab="${tab}"]`)?.click();
  }

  function matches(command, query) {
    const haystack = `${command.label} ${command.hint} ${command.keywords}`.toLowerCase();
    return query.split(/\s+/).filter(Boolean).every((part) => haystack.includes(part));
  }

  function filtered() {
    const query = ($("personCommandPaletteInput")?.value || "").trim().toLowerCase();
    return query ? commands.filter((command) => matches(command, query)) : commands;
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
      label.textContent = command.label;
      const hint = document.createElement("span");
      hint.textContent = command.hint;
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
    if (context) {
      const person = selectedPerson();
      context.textContent = person ? `Valgt person · ${person}` : "Ingen person valgt.";
    }
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