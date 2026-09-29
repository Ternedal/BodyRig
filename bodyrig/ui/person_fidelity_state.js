(() => {
  const STATES = new Set(["ready", "blocked", "checking", "unknown"]);
  const REVIEW_STATES = new Set(["ready", "required", "blocked", "checking", "unknown"]);

  function read() {
    const root = document.getElementById("bodyControlStrip");
    if (!root || root.dataset.stateVersion !== "1") return null;

    const state = String(root.dataset.fidelityState || "").trim();
    const review = String(root.dataset.fidelityReviewState || "").trim();
    const label = String(root.dataset.fidelityLabel || "").trim();

    if (!STATES.has(state) || !REVIEW_STATES.has(review) || label.length > 240) {
      return null;
    }
    return Object.freeze({ state, review, label });
  }

  function requiresAttention(value = read()) {
    return value?.state === "blocked" || value?.review === "required";
  }

  window.BodyRigFidelityState = Object.freeze({
    read,
    requiresAttention,
  });
})();
