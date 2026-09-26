(() => {
  const $ = (id) => document.getElementById(id);

  function text(id) {
    return ($(id)?.textContent || "").replace(/\s+/g, " ").trim();
  }

  function firstClickable(root) {
    if (!root) return null;
    return root.querySelector("button:not([disabled]), a[href]");
  }

  function targetTabFromNode(node) {
    if (!node) return null;
    const tabButton = node.closest?.("[data-tab], [data-target-tab], [data-activity-tab], [data-topology-tab]");
    if (tabButton) {
      return tabButton.dataset.tab
        || tabButton.dataset.targetTab
        || tabButton.dataset.activityTab
        || tabButton.dataset.topologyTab
        || null;
    }
    const href = node.getAttribute?.("href") || "";
    if (href.includes("personality")) return "personality";
    return null;
  }

  function inferredTab(copy) {
    const value = copy.toLowerCase();
    if (/voice|stemme/.test(value)) return "voice";
    if (/personality|personlighed/.test(value)) return "personality";
    if (/photoreal|exavatar|body|krop|source|stash/.test(value)) return "body";
    if (/digital twin|m1|m2|m3|m4|m5|m6|drift|operator|launch|job/.test(value)) return "operations";
    if (/assemble|saml|revision|compatibility|audition/.test(value)) return "assemble";
    return "overview";
  }

  function openTab(tab) {
    document.querySelector(`.tab[data-tab="${tab}"]`)?.click();
  }

  function refresh() {
    const attention = $("overviewCockpitAttention");
    const next = $("overviewCockpitNext");
    const attentionVisible = attention && !attention.classList.contains("hidden") && text("overviewCockpitAttention");
    const source = attentionVisible ? attention : next;
    const copy = (source?.textContent || "").replace(/\s+/g, " ").trim();

    const title = $("personMissionTitle");
    const detail = $("personMissionDetail");
    const action = $("personMissionAction");
    const root = $("personMissionControl");
    if (!title || !detail || !action || !root) return;

    if (!copy) {
      title.textContent = "Afventer pipeline-status";
      detail.textContent = "Mission Control spejler Person-pipelinens eksisterende blocker/next-action-logik.";
      action.disabled = true;
      action.dataset.targetTab = "";
      root.classList.remove("attention");
      return;
    }

    const clickable = firstClickable(source);
    const tab = targetTabFromNode(clickable) || inferredTab(copy);
    const label = attentionVisible ? "Kræver handling" : "Næste handling";

    title.textContent = label;
    detail.textContent = copy;
    action.disabled = false;
    action.dataset.targetTab = tab;
    action.textContent = tab === "operations" ? "Åbn Drift" : "Åbn relevant kontrol";
    root.classList.toggle("attention", Boolean(attentionVisible));
  }

  $("personMissionAction")?.addEventListener("click", () => {
    const tab = $("personMissionAction")?.dataset.targetTab;
    if (tab) openTab(tab);
  });

  for (const id of ["overviewCockpitAttention", "overviewCockpitNext"]) {
    const node = $(id);
    if (node) {
      new MutationObserver(refresh).observe(node, {
        childList: true,
        characterData: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["class"],
      });
    }
  }

  refresh();
})();