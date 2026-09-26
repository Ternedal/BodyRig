(() => {
  const $ = (id) => document.getElementById(id);
  let open = false;
  let refreshQueued = false;

  const ACTIVITY_KINDS = new Set(["attention", "job", "launch", "photoreal"]);
  const ACTIVITY_STATES = new Set([
    "action", "blocked", "offline", "unknown", "running", "stalled",
    "uploading", "queued", "needs_speaker", "needs_reference", "cancelling",
    "succeeded", "failed", "canceled", "interrupted", "complete", "required",
    "human-review-required", "operator-input-required", "no-run",
    "workspace-ready", "preprocess", "training-ready", "training",
    "neutral-render", "human-review", "not-started", "not-applicable",
  ]);

  function boundedDataset(root, key, limit, { required = false } = {}) {
    const value = String(root?.dataset?.[key] || "").trim();
    if (!value) return required ? null : "";
    if (value.length > limit || /[\u0000-\u001f\u007f]/.test(value)) return null;
    return value;
  }

  function integerDataset(root, key) {
    const raw = String(root?.dataset?.[key] || "").trim();
    if (!/^\d+$/.test(raw)) return null;
    const value = Number(raw);
    return Number.isSafeInteger(value) && value >= 0 ? value : null;
  }

  function activitySnapshot(node, expectedKind = null) {
    if (!node || node.dataset?.activityStateVersion !== "1") return null;
    const kind = boundedDataset(node, "activityKind", 32, { required: true });
    const id = boundedDataset(node, "activityId", 256, { required: true });
    const title = boundedDataset(node, "activityTitle", 200, { required: true });
    const detail = boundedDataset(node, "activityDetail", 1600);
    const state = boundedDataset(node, "activityState", 64);
    const actionLabel = boundedDataset(node, "activityActionLabel", 120);
    const unseenRaw = String(node.dataset?.activityUnseen || "");
    if (!kind || !id || !title || !ACTIVITY_KINDS.has(kind)) return null;
    if (detail === null || state === null || actionLabel === null) return null;
    if (expectedKind && kind !== expectedKind) return null;
    if (state && !ACTIVITY_STATES.has(state)) return null;
    if (unseenRaw && !["0", "1"].includes(unseenRaw)) return null;
    return {
      kind,
      id,
      title,
      detail: detail === null ? "" : detail,
      state: state === null ? "" : state,
      actionLabel: actionLabel === null ? "" : actionLabel,
      unseen: unseenRaw === "1",
    };
  }

  function attentionCounts() {
    const badge = $("operatorAttentionBadge");
    if (!badge || badge.dataset.stateVersion !== "1") {
      return { active: 0, unseen: 0 };
    }
    const active = integerDataset(badge, "activeCount");
    const unseen = integerDataset(badge, "unseenCount");
    if (active === null || unseen === null || unseen > active) {
      return { active: 0, unseen: 0 };
    }
    return { active, unseen };
  }

  function personName() {
    const hud = $("personHud");
    if (!hud || hud.dataset.stateVersion !== "1") return "Ingen verificeret person";
    const name = boundedDataset(hud, "personName", 160);
    return name || "Ingen verificeret person";
  }

  function empty(target, message) {
    target.replaceChildren();
    const node = document.createElement("div");
    node.className = "person-activity-empty";
    node.textContent = message;
    target.appendChild(node);
  }

  function resolveDriftSource(sourceNode) {
    if (sourceNode?.isConnected) return sourceNode;
    const snapshot = activitySnapshot(sourceNode);
    if (!snapshot || !["job", "launch"].includes(snapshot.kind)) return null;
    const host = snapshot.kind === "job" ? $("operatorJobs") : $("operatorLaunches");
    if (!host) return null;
    return [...host.children].find((node) => {
      const candidate = activitySnapshot(node, snapshot.kind);
      return candidate?.id === snapshot.id;
    }) || null;
  }

  function openDriftSource(sourceNode) {
    const initial = resolveDriftSource(sourceNode);
    if (!initial) {
      scheduleRefresh();
      return;
    }
    document.querySelector('.tab[data-tab="operations"]')?.click();
    setOpen(false);
    requestAnimationFrame(() => {
      const target = resolveDriftSource(sourceNode);
      if (!target) {
        scheduleRefresh();
        return;
      }
      const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
      target.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
      target.classList.add("activity-focus");
      window.setTimeout(() => {
        if (target.isConnected) target.classList.remove("activity-focus");
      }, 1800);
    });
  }

  function appendSnapshotItem(target, snapshot, { sourceNode = null, actionLabel = "" } = {}) {
    const item = document.createElement("div");
    item.className = `person-activity-item${sourceNode ? " person-activity-drilldown-item" : ""}`;
    const copy = document.createElement("div");
    copy.className = "person-activity-item-text";

    const title = document.createElement("strong");
    title.textContent = snapshot.title;
    copy.appendChild(title);
    if (snapshot.detail) {
      const detail = document.createElement("div");
      detail.className = "person-activity-item-detail";
      detail.textContent = snapshot.detail;
      copy.appendChild(detail);
    }
    item.appendChild(copy);

    if (sourceNode && actionLabel) {
      const action = document.createElement("button");
      action.type = "button";
      action.className = "person-activity-action";
      action.textContent = actionLabel;
      action.addEventListener("click", () => openDriftSource(sourceNode));
      item.appendChild(action);
    }
    target.appendChild(item);
  }

  function mirrorStructuredRows(sourceId, targetId, kind, limit, emptyMessage) {
    const source = $(sourceId);
    const target = $(targetId);
    if (!target) return 0;
    if (!source) {
      empty(target, emptyMessage);
      return 0;
    }
    const rows = [...source.children]
      .map((node) => ({ node, snapshot: activitySnapshot(node, kind) }))
      .filter((item) => item.snapshot !== null);
    if (!rows.length) {
      empty(target, emptyMessage);
      return 0;
    }

    target.replaceChildren();
    for (const { node, snapshot } of rows.slice(0, limit)) {
      appendSnapshotItem(target, snapshot, {
        sourceNode: node,
        actionLabel: snapshot.actionLabel || "Åbn i Drift",
      });
    }
    return rows.length;
  }

  function mirrorAttention() {
    const source = $("operatorAttentionItems");
    const target = $("personActivityAttention");
    if (!target) return 0;
    if (!source) {
      empty(target, "Ingen aktuelle operator-handlinger.");
      return 0;
    }

    const rows = [...source.children]
      .map((node) => ({ node, snapshot: activitySnapshot(node, "attention") }))
      .filter((item) => item.snapshot !== null);
    if (!rows.length) {
      empty(target, "Ingen aktuelle operator-handlinger.");
      return 0;
    }

    target.replaceChildren();
    for (const { node, snapshot } of rows.slice(0, 5)) {
      const item = document.createElement("div");
      item.className = `person-activity-item person-activity-attention-item${snapshot.unseen ? " new-attention" : ""}`;

      const copy = document.createElement("div");
      copy.className = "person-activity-item-text";
      const title = document.createElement("strong");
      title.textContent = snapshot.title;
      copy.appendChild(title);
      if (snapshot.detail) {
        const detail = document.createElement("div");
        detail.className = "person-activity-item-detail";
        detail.textContent = snapshot.detail;
        copy.appendChild(detail);
      }
      item.appendChild(copy);

      if (snapshot.actionLabel) {
        const sourceAction = node.querySelector("button");
        if (sourceAction) {
          const action = document.createElement("button");
          action.type = "button";
          action.className = "person-activity-action";
          action.textContent = snapshot.actionLabel;
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
      }
      target.appendChild(item);
    }
    return rows.length;
  }

  function photorealStateLabel(state) {
    return ({
      running: "Kører",
      stalled: "Mulig stall",
      complete: "Komplet",
      required: "Næste trin",
      "human-review-required": "Human review",
      "operator-input-required": "Input kræves",
      blocked: "Blokeret",
      offline: "Offline",
      "no-run": "Ingen run",
    })[state] || state || "Ukendt";
  }

  function mirrorPhotoreal() {
    const target = $("personActivityPhotoreal");
    if (!target) return;
    const snapshot = activitySnapshot($("operator-photoreal-summary"), "photoreal");
    target.replaceChildren();

    if (!snapshot) {
      const missing = document.createElement("div");
      missing.className = "person-activity-empty";
      missing.textContent = "Photoreal structured state er endnu ikke tilgængelig.";
      target.appendChild(missing);
      return;
    }

    const top = document.createElement("div");
    top.className = "person-activity-photoreal-top";
    const label = document.createElement("strong");
    label.textContent = snapshot.title;
    const state = document.createElement("span");
    state.className = "badge muted";
    state.textContent = photorealStateLabel(snapshot.state);
    top.append(label, state);

    const body = document.createElement("div");
    body.className = "fine-print";
    body.textContent = snapshot.detail || "Ingen live detail endnu.";
    target.append(top, body);
  }

  function refresh() {
    refreshQueued = false;
    const attention = mirrorAttention();
    const jobs = mirrorStructuredRows("operatorJobs", "personActivityJobs", "job", 5, "Ingen verificerede jobs.");
    const launches = mirrorStructuredRows("operatorLaunches", "personActivityLaunches", "launch", 5, "Ingen verificerede operator launches.");
    mirrorPhotoreal();

    const counts = attentionCounts();
    const count = Math.max(counts.active, attention);
    const unseen = counts.unseen;
    if ($("personActivityAttentionCount")) $("personActivityAttentionCount").textContent = String(count);
    if ($("personActivityToggleCount")) $("personActivityToggleCount").textContent = String(count);
    $("personActivityToggle")?.classList.toggle("attention", count > 0);
    $("personActivityToggle")?.classList.toggle("has-new", unseen > 0);
    if ($("personActivityToggle")) {
      $("personActivityToggle").title = unseen > 0
        ? `${unseen} nye operator-punkt${unseen === 1 ? "" : "er"}`
        : "Live Activity";
    }

    const meta = $("personActivityMeta");
    if (meta) {
      meta.textContent = `${personName()} · ${jobs} job(s) · ${launches} launch(es) fra structured Drift-state${unseen ? ` · ${unseen} nye` : ""}`;
    }
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
    "operatorLaunches",
    "operator-photoreal-summary",
    "personHud",
  ];
  for (const id of observed) {
    const node = $(id);
    if (node) new MutationObserver(scheduleRefresh).observe(node, {
      childList: true,
      attributes: true,
      subtree: true,
    });
  }

  function handleAttentionDelta(event) {
    scheduleRefresh();
    const unseen = Number(event?.detail?.unseen_count || 0);
    if (open && unseen > 0) {
      requestAnimationFrame(() => {
        window.dispatchEvent(new CustomEvent("bodyrig:attention-seen"));
      });
    }
  }

  window.addEventListener("bodyrig:attention-delta", handleAttentionDelta);
  refresh();
})();
