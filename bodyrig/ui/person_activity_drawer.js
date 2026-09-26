(() => {
  const $ = (id) => document.getElementById(id);
  let open = false;
  let refreshQueued = false;

  function cleanText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function empty(target, message) {
    target.replaceChildren();
    const node = document.createElement("div");
    node.className = "person-activity-empty";
    node.textContent = message;
    target.appendChild(node);
  }

  function mirrorChildren(sourceId, targetId, limit, emptyMessage) {
    const source = $(sourceId);
    const target = $(targetId);
    if (!target) return 0;
    if (!source) {
      empty(target, emptyMessage);
      return 0;
    }
    const nodes = [...source.children].filter((node) => cleanText(node.textContent));
    if (!nodes.length) {
      empty(target, emptyMessage);
      return 0;
    }
    target.replaceChildren();
    for (const sourceNode of nodes.slice(0, limit)) {
      const item = document.createElement("div");
      item.className = "person-activity-item";
      const text = document.createElement("div");
      text.className = "person-activity-item-text";
      text.textContent = cleanText(sourceNode.textContent);
      item.appendChild(text);
      target.appendChild(item);
    }
    return nodes.length;
  }

  function mirrorAttention() {
    const source = $("operatorAttentionItems");
    const target = $("personActivityAttention");
    if (!target) return 0;
    if (!source) {
      empty(target, "Ingen aktuelle operator-handlinger.");
      return 0;
    }
    const nodes = [...source.children].filter((node) => cleanText(node.textContent));
    if (!nodes.length) {
      empty(target, "Ingen aktuelle operator-handlinger.");
      return 0;
    }
    target.replaceChildren();
    for (const sourceNode of nodes.slice(0, 5)) {
      const item = document.createElement("div");
      item.className = `person-activity-item person-activity-attention-item${sourceNode.classList.contains("new-attention") ? " new-attention" : ""}`;

      const sourceAction = sourceNode.querySelector("button");
      const copySource = sourceNode.cloneNode(true);
      copySource.querySelectorAll("button").forEach((button) => button.remove());

      const text = document.createElement("div");
      text.className = "person-activity-item-text";
      text.textContent = cleanText(copySource.textContent);
      item.appendChild(text);

      if (sourceAction) {
        const action = document.createElement("button");
        action.type = "button";
        action.className = "person-activity-action";
        action.textContent = cleanText(sourceAction.textContent) || "Åbn";
        action.addEventListener("click", () => {
          if (!sourceAction.isConnected) {
            scheduleRefresh();
            return;
          }
          sourceAction.click();
          setOpen(false);
        });
        item.appendChild(action);
      }
      target.appendChild(item);
    }
    return nodes.length;
  }

  function mirrorPhotoreal() {
    const target = $("personActivityPhotoreal");
    if (!target) return;
    const badge = cleanText($("operator-photoreal-badge")?.textContent);
    const summary = cleanText($("operator-photoreal-summary")?.textContent);
    const detail = cleanText($("operator-photoreal-detail")?.textContent);
    target.replaceChildren();

    const top = document.createElement("div");
    top.className = "person-activity-photoreal-top";
    const label = document.createElement("strong");
    label.textContent = summary || "Photoreal-status ukendt";
    const state = document.createElement("span");
    state.className = "badge muted";
    state.textContent = badge || "Ukendt";
    top.append(label, state);

    const body = document.createElement("div");
    body.className = "fine-print";
    body.textContent = detail || "Ingen live detail endnu.";
    target.append(top, body);
  }

  function attentionCount() {
    const badge = cleanText($("operatorAttentionBadge")?.textContent);
    const match = badge.match(/\d+/);
    if (match) return Number(match[0]);
    return [...($("operatorAttentionItems")?.children || [])].length;
  }

  function unseenAttentionCount() {
    const badge = $("operatorAttentionBadge");
    const declared = Number(badge?.dataset?.unseenCount);
    if (Number.isInteger(declared) && declared >= 0) return declared;
    return [...document.querySelectorAll("#operatorAttentionItems .new-attention")].length;
  }

  function refresh() {
    refreshQueued = false;
    const attention = mirrorAttention();
    const jobs = mirrorChildren("operatorJobs", "personActivityJobs", 5, "Ingen renderede jobs.");
    const launches = mirrorChildren("operatorLaunches", "personActivityLaunches", 5, "Ingen renderede operator launches.");
    mirrorPhotoreal();

    const count = Math.max(attentionCount(), attention);
    const unseen = unseenAttentionCount();
    if ($("personActivityAttentionCount")) $("personActivityAttentionCount").textContent = String(count);
    if ($("personActivityToggleCount")) $("personActivityToggleCount").textContent = String(count);
    $("personActivityToggle")?.classList.toggle("attention", count > 0);
    $("personActivityToggle")?.classList.toggle("has-new", unseen > 0);
    if ($("personActivityToggle")) {
      $("personActivityToggle").title = unseen > 0
        ? `${unseen} nye operator-punkt${unseen === 1 ? "" : "er"}`
        : "Live Activity";
    }

    const person = cleanText($("personName")?.textContent) || "Ingen person";
    const meta = $("personActivityMeta");
    if (meta) meta.textContent = `${person} · ${jobs} job(s) · ${launches} launch(es) renderet i Drift${unseen ? ` · ${unseen} nye` : ""}`;
  }

  function scheduleRefresh() {
    if (refreshQueued) return;
    refreshQueued = true;
    requestAnimationFrame(refresh);
  }

  function setOpen(next) {
    open = Boolean(next);
    $("personActivityDrawer")?.classList.toggle("open", open);
    $("personActivityDrawer")?.setAttribute("aria-hidden", String(!open));
    $("personActivityToggle")?.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("person-activity-open", open);
    if (open) {
      scheduleRefresh();
      requestAnimationFrame(() => {
        window.dispatchEvent(new CustomEvent("bodyrig:attention-seen"));
        $("personActivityToggle")?.classList.remove("has-new");
      });
    }
  }

  $("personActivityToggle")?.addEventListener("click", () => setOpen(!open));
  $("personActivityClose")?.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && open) setOpen(false);
  });
  for (const button of document.querySelectorAll("[data-activity-tab]")) {
    button.addEventListener("click", () => {
      document.querySelector(`.tab[data-tab="${button.dataset.activityTab}"]`)?.click();
      setOpen(false);
    });
  }

  const observed = [
    "operatorAttentionItems",
    "operatorAttentionBadge",
    "operatorJobs",
    "operatorJobsStatus",
    "operatorLaunches",
    "operatorLaunchesStatus",
    "operator-photoreal-badge",
    "operator-photoreal-summary",
    "operator-photoreal-detail",
    "personName",
  ];
  for (const id of observed) {
    const node = $(id);
    if (node) new MutationObserver(scheduleRefresh).observe(node, {
      childList: true,
      characterData: true,
      attributes: id === "operatorAttentionBadge",
      attributeFilter: id === "operatorAttentionBadge" ? ["data-unseen-count", "class"] : undefined,
      subtree: true,
    });
  }

  window.addEventListener("bodyrig:attention-delta", scheduleRefresh);
  refresh();
})();