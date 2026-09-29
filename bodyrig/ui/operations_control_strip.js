(() => {
  const $ = (id) => document.getElementById(id);
  const ALLOWED = {
    health: new Set(["ready", "blocked", "checking"]),
    attention: new Set(["ready", "attention", "checking"]),
    execution: new Set(["ready", "attention", "checking"]),
    twin: new Set(["ready", "blocked", "unknown", "checking"]),
    priority: new Set(["ready", "attention", "blocked", "checking"]),
  };

  function setChip(id, state, active) {
    const chip = $(id);
    if (!chip) return;
    const node = chip.querySelector(".chip-state");
    if (node) node.textContent = state || "Ukendt";
    chip.classList.toggle("active", Boolean(active));
  }

  function readField(root, key) {
    const state = String(root.dataset[key + "State"] || "").trim();
    const label = String(root.dataset[key + "Label"] || "").trim();
    if (!ALLOWED[key]?.has(state) || !label || label.length > 240) return null;
    return { state, label };
  }

  function structuredState() {
    const root = $("operationsControlStrip");
    if (!root || root.dataset.stateVersion !== "1") return null;
    const health = readField(root, "health");
    const attention = readField(root, "attention");
    const execution = readField(root, "execution");
    const twin = readField(root, "twin");
    const priority = readField(root, "priority");
    if (!health || !attention || !execution || !twin || !priority) return null;
    return { health, attention, execution, twin, priority };
  }

  function refresh() {
    const state = structuredState();
    const next = $("operationsControlNext");
    if (!state) {
      setChip("operationsControlHealth", "Ukendt", false);
      setChip("operationsControlAttention", "Ukendt", false);
      setChip("operationsControlExecution", "Ukendt", false);
      setChip("operationsControlTwin", "Ukendt", false);
      if (next) next.textContent = "Afventer authoritative Drift-snapshot…";
      return;
    }

    setChip("operationsControlHealth", state.health.label, state.health.state === "ready");
    setChip("operationsControlAttention", state.attention.label, state.attention.state === "ready");
    setChip("operationsControlExecution", state.execution.label, state.execution.state === "ready");
    setChip("operationsControlTwin", state.twin.label, state.twin.state === "ready");
    if (next) next.textContent = state.priority.label;
  }

  $("operationsControlHealth")?.addEventListener("click", () =>
    window.BodyRigPersonNavigation?.focusElement($("operatorRefresh"), { block: "center" })
  );
  $("operationsControlAttention")?.addEventListener("click", () =>
    window.BodyRigPersonNavigation?.focusElement($("operatorAttentionItems"))
  );
  $("operationsControlExecution")?.addEventListener("click", () =>
    window.BodyRigPersonNavigation?.focusElement($("operatorJobs"))
  );
  $("operationsControlTwin")?.addEventListener("click", () =>
    window.BodyRigPersonNavigation?.focusElement($("operator-digital-twin-stages"))
  );

  const root = $("operationsControlStrip");
  if (root) {
    new MutationObserver(refresh).observe(root, { attributes: true });
  }
  refresh();
})();
