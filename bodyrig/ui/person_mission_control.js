(() => {
  const $ = (id) => document.getElementById(id);
  function missionState() {
    return window.BodyRigMissionState?.read() || null;
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

  function openTargetSection(state) {
    if (state.targetSection !== "fidelity-command-center") return;
    window.BodyRigPersonNavigation?.focusFidelityCenter();
  }

  $("personMissionAction")?.addEventListener("click", () => {
    const state = missionState();
    if (!window.BodyRigMissionState?.actionable(state)) return;
    document.querySelector(`.tab[data-tab="${state.targetTab}"]`)?.click();
    openTargetSection(state);
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
        "data-mission-target-section",
      ],
    });
  }

  refresh();
})();