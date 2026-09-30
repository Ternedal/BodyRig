(() => {
  const COMPONENT_STATES = new Set(["bound", "unbound", "unknown"]);

  function integerDataset(root, key) {
    const raw = String(root?.dataset?.[key] || "").trim();
    if (!/^\d+$/.test(raw)) return null;
    const value = Number(raw);
    return Number.isSafeInteger(value) ? value : null;
  }

  function read() {
    const root = document.getElementById("personHud");
    if (!root || root.dataset.stateVersion !== "1") return null;

    const name = String(root.dataset.personName || "").trim();
    const revision = String(root.dataset.personRevision || "").trim();
    const complete = integerDataset(root, "pipelineComplete");
    const total = integerDataset(root, "pipelineTotal");
    const body = String(root.dataset.bodyState || "").trim();
    const voice = String(root.dataset.voiceState || "").trim();
    const personality = String(root.dataset.personalityState || "").trim();

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

    return Object.freeze({ name, revision, complete, total, body, voice, personality });
  }

  window.BodyRigPersonState = Object.freeze({
    read,
  });
})();
