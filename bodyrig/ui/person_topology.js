(() => {
  const $ = (id) => document.getElementById(id);
  const NODE_STATES = new Set(["bound", "unbound", "invalid", "ready", "not-ready", "unknown"]);

  function setNode(id, active, stateText, invalid = false) {
    const node = $(id);
    if (!node) return;
    node.classList.toggle("active", Boolean(active));
    node.classList.toggle("inactive", !active);
    node.classList.toggle("invalid", Boolean(invalid));
    const state = node.querySelector(".node-state");
    if (state) state.textContent = stateText || "—";
  }

  function readField(root, key) {
    const state = String(root?.dataset?.[key + "State"] || "").trim();
    const label = String(root?.dataset?.[key + "Label"] || "").trim();
    if (!NODE_STATES.has(state) || label.length > 500) return null;
    return { state, label };
  }

  function structuredTopologyState() {
    const root = document.querySelector(".person-topology-card");
    if (!root || root.dataset.stateVersion !== "1") return null;

    const source = readField(root, "source");
    const body = readField(root, "body");
    const voice = readField(root, "voice");
    const personality = readField(root, "personality");
    const core = readField(root, "core");
    const twin = readField(root, "twin");
    if (!source || !body || !voice || !personality || !core || !twin) return null;

    return { source, body, voice, personality, core, twin };
  }

  function fidelityState() {
    const root = $("bodyControlStrip");
    if (!root || root.dataset.stateVersion !== "1") return null;
    const state = String(root.dataset.fidelityState || "").trim();
    const review = String(root.dataset.fidelityReviewState || "").trim();
    const label = String(root.dataset.fidelityLabel || "").trim();
    if (!new Set(["ready", "blocked", "checking", "unknown"]).has(state)) return null;
    if (!new Set(["ready", "required", "blocked", "checking", "unknown"]).has(review)) return null;
    if (label.length > 240) return null;
    return { state, review, label };
  }

  function refresh() {
    const state = structuredTopologyState();
    const badge = $("personTopologyBadge");
    const coreName = $("personTopologyCoreName");

    if (!state) {
      setNode("personTopologySource", false, "Ukendt");
      setNode("personTopologyBody", false, "Ukendt");
      const bodyNode = $("personTopologyBody");
      if (bodyNode) {
        bodyNode.classList.remove("fidelity-attention");
        bodyNode.title = "Åbn BodyRig";
        bodyNode.setAttribute("aria-label", "BodyRig");
      }
      setNode("personTopologyVoice", false, "Ukendt");
      setNode("personTopologyPersonality", false, "Ukendt");
      setNode("personTopologyCore", false, "Ukendt");
      setNode("personTopologyTwin", false, "Ukendt");
      if (coreName) coreName.textContent = "Ikke verificeret";
      if (badge) {
        badge.textContent = "Ukendt";
        badge.classList.add("muted");
      }
      return;
    }

    const fidelity = fidelityState();
    const sourceActive = state.source.state === "bound";
    const bodyActive = state.body.state === "bound";
    const voiceActive = state.voice.state === "bound";
    const personalityActive = state.personality.state === "bound";
    const coreActive = state.core.state === "bound";
    const coreInvalid = state.core.state === "invalid";
    const twinReady = state.twin.state === "ready";

    setNode("personTopologySource", sourceActive, sourceActive ? state.source.label : "Ingen binding");
    const bodyLabel = bodyActive
      ? [state.body.label, fidelity?.label].filter(Boolean).join(" · ")
      : "Ingen aktiv binding";
    setNode("personTopologyBody", bodyActive, bodyLabel);
    const bodyNode = $("personTopologyBody");
    if (bodyNode) {
      const fidelityAttention = fidelity?.state === "blocked" || fidelity?.review === "required";
      bodyNode.classList.toggle("fidelity-attention", fidelityAttention);
      bodyNode.title = fidelity?.label
        ? `BodyRig · Fidelity: ${fidelity.label}`
        : "Åbn BodyRig";
      bodyNode.setAttribute(
        "aria-label",
        fidelityAttention && fidelity?.label
          ? `BodyRig kræver handling · ${fidelity.label}`
          : (fidelity?.label ? `BodyRig · ${fidelity.label}` : "BodyRig")
      );
    }
    setNode("personTopologyVoice", voiceActive, voiceActive ? state.voice.label : "Ingen aktiv binding");
    setNode("personTopologyPersonality", personalityActive, personalityActive ? state.personality.label : "Ingen aktiv binding");
    setNode(
      "personTopologyCore",
      coreActive,
      coreInvalid ? "Ugyldig canonical binding" : (coreActive ? "Aktiv canonical revision" : "Ikke samlet"),
      coreInvalid
    );
    setNode("personTopologyTwin", twinReady, state.twin.label || (twinReady ? "M6 klar" : "Ikke M6-klar"));

    if (coreName) {
      coreName.textContent = coreActive
        ? state.core.label
        : (coreInvalid ? "Ugyldig binding" : "Ikke samlet");
    }

    const completed = [
      sourceActive,
      bodyActive,
      voiceActive,
      personalityActive,
      coreActive,
      twinReady,
    ].filter(Boolean).length;

    if (badge) {
      badge.textContent = twinReady && completed === 6 ? "Topology locked" : `${completed}/6 linked`;
      badge.classList.toggle("muted", !(twinReady && completed === 6));
    }
  }

  for (const button of document.querySelectorAll("[data-topology-tab]")) {
    button.addEventListener("click", () => {
      document.querySelector(`.tab[data-tab="${button.dataset.topologyTab}"]`)?.click();
      if (button.id === "personTopologyBody") {
        const fidelity = fidelityState();
        if (fidelity?.state === "blocked" || fidelity?.review === "required") {
          window.BodyRigPersonNavigation?.focusFidelityCenter();
        }
      }
    });
  }

  const bodyControl = $("bodyControlStrip");
  if (bodyControl) {
    new MutationObserver(refresh).observe(bodyControl, {
      attributes: true,
      attributeFilter: [
        "data-state-version",
        "data-fidelity-state",
        "data-fidelity-review-state",
        "data-fidelity-label",
      ],
    });
  }

  const root = document.querySelector(".person-topology-card");
  if (root) {
    new MutationObserver(refresh).observe(root, {
      attributes: true,
      attributeFilter: [
        "data-state-version",
        "data-source-state",
        "data-source-label",
        "data-body-state",
        "data-body-label",
        "data-voice-state",
        "data-voice-label",
        "data-personality-state",
        "data-personality-label",
        "data-core-state",
        "data-core-label",
        "data-twin-state",
        "data-twin-label",
      ],
    });
  }

  refresh();
})();