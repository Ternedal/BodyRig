(() => {
  const MISSION_KINDS = new Set(["unknown", "attention", "next", "complete"]);
  const TARGET_TABS = new Set(["overview", "body", "voice", "personality", "assemble", "history", "operations"]);

  function read() {
    const root = document.getElementById("personMissionControl");
    if (!root || root.dataset.stateVersion !== "1") return null;

    const kind = String(root.dataset.missionKind || "").trim();
    const title = String(root.dataset.missionTitle || "").trim();
    const detail = String(root.dataset.missionDetail || "").trim();
    const targetTab = String(root.dataset.missionTargetTab || "").trim();
    const actionLabel = String(root.dataset.missionActionLabel || "").trim();
    const targetSection = String(root.dataset.missionTargetSection || "").trim();

    if (!MISSION_KINDS.has(kind) || !title || !detail) return null;
    if (title.length > 160 || detail.length > 1000 || actionLabel.length > 120 || targetSection.length > 80) return null;
    if (targetTab && !TARGET_TABS.has(targetTab)) return null;
    if ((kind === "attention" || kind === "next") && !targetTab) return null;
    if ((kind === "unknown" || kind === "complete") && targetTab) return null;
    if (targetSection && targetSection !== "fidelity-command-center") return null;
    if (targetSection && targetTab !== "body") return null;

    return Object.freeze({ kind, title, detail, targetTab, actionLabel, targetSection });
  }

  function actionable(value = read()) {
    return value?.kind === "attention" || value?.kind === "next";
  }

  window.BodyRigMissionState = Object.freeze({
    read,
    actionable,
  });
})();
