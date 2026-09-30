(() => {
  function integerDataset(root, key) {
    const raw = String(root?.dataset?.[key] || "").trim();
    if (!/^\d+$/.test(raw)) return null;
    const value = Number(raw);
    return Number.isSafeInteger(value) && value >= 0 ? value : null;
  }

  function read() {
    const badge = document.getElementById("operatorAttentionBadge");
    if (!badge || badge.dataset.stateVersion !== "1") {
      return Object.freeze({ active: 0, unseen: 0 });
    }

    const active = integerDataset(badge, "activeCount");
    const unseen = integerDataset(badge, "unseenCount");
    if (active === null || unseen === null || unseen > active) {
      return Object.freeze({ active: 0, unseen: 0 });
    }

    return Object.freeze({ active, unseen });
  }

  window.BodyRigAttentionState = Object.freeze({
    read,
  });
})();
