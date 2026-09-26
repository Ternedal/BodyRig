(() => {
  const $ = (id) => document.getElementById(id);
  const MISSION_KINDS = new Set(["unknown", "attention", "next", "complete"]);
  const TARGET_TABS = new Set(["overview", "body", "voice", "personality", "assemble", "history", "operations"]);

  function missionState() {
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

  function renderUnknown() {
    const title = $("personMissionTitle");
    const detail = $("personMissionDetail");
    const action = $("personMissionAction");
    const root = $("personMissionControl");
    if (!title || !detail || !action || !root) return;

    title.textContent = "Afventer pipeline-status";
    detail.textContent = "Mission Control afventer et struktureret Overview-snapshot.";
    action.disabled = true;
    action.dataset.targetTab = "";
    action.textContent = "Åbn relevant kontrol";
    root.classList.remove("attention");
  }

  function refresh() {
    const state = missionState();
    if (!state) {
      renderUnknown();
      return;
    }

    const title = $("personMissionTitle");
    const detail = $("personMissionDetail");
    const action = $("personMissionAction");
    const root = $("personMissionControl");
    if (!title || !detail || !action || !root) return;

    title.textContent = state.title;
    detail.textContent = state.detail;
    root.classList.toggle("attention", state.kind === "attention");

    const actionable = state.kind === "attention" || state.kind === "next";
    action.disabled = !actionable;
    action.dataset.targetTab = actionable ? state.targetTab : "";
    action.textContent = actionable
      ? (state.actionLabel || (state.targetTab === "operations" ? "Åbn Drift" : "Åbn relevant kontrol"))
      : (state.kind === "complete" ? "Ingen handling nødvendig" : "Åbn relevant kontrol");
  }

  $("personMissionAction")?.addEventListener("click", () => {
    const state = missionState();
    if (!state || (state.kind !== "attention" && state.kind !== "next")) return;
    document.querySelector(`.tab[data-tab="${state.targetTab}"]`)?.click();
  });

  const root = $("personMissionControl");
  if (root) {
    new MutationObserver(refresh).observe(root, {
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

  refresh();
})();