(() => {
  let serial = 0;

  function personId() {
    return (document.getElementById("personId")?.textContent || "").trim();
  }

  async function readJson(url) {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    if (!response.ok) throw new Error(payload?.detail || `HTTP ${response.status}`);
    return payload;
  }

  function activeBundle(profile) {
    const id = String(profile?.active_person_revision || "");
    if (!id) return null;
    return (Array.isArray(profile?.person_revisions) ? profile.person_revisions : [])
      .find((item) => String(item?.revision_id || "") === id) || null;
  }

  function stageNode(definition) {
    const node = document.createElement("button");
    node.type = "button";
    node.className = `person-cockpit-stage ${definition.state}`;
    node.dataset.targetTab = definition.tab || "";

    const top = document.createElement("div");
    top.className = "person-cockpit-stage-top";
    const label = document.createElement("strong");
    label.textContent = definition.label;
    const badge = document.createElement("span");
    badge.className = `badge${definition.state === "complete" ? "" : " muted"}`;
    badge.textContent = definition.status;
    top.append(label, badge);

    const detail = document.createElement("div");
    detail.className = "fine-print";
    detail.textContent = definition.detail;

    node.append(top, detail);
    if (definition.tab) {
      node.addEventListener("click", () => {
        document.querySelector(`.tab[data-tab="${definition.tab}"]`)?.click();
      });
    } else {
      node.disabled = true;
    }
    return node;
  }

  function candidateState(items, activeId) {
    const list = Array.isArray(items) ? items : [];
    if (activeId) return { state: "complete", status: "Aktiv", detail: `${activeId} · ${list.length} kandidat(er)` };
    if (list.length) return { state: "ready", status: "Kandidat klar", detail: `${list.length} kandidat(er), men ingen aktiv samlet binding` };
    return { state: "missing", status: "Mangler", detail: "Ingen kandidat endnu" };
  }

  function nextAction(stages, digitalTwin) {
    const ordered = ["source", "body", "voice", "personality", "assemble"];
    for (const key of ordered) {
      const stage = stages.find((item) => item.key === key);
      if (stage && stage.state !== "complete") return stage;
    }
    if (digitalTwin && digitalTwin.digital_twin_ready !== true) {
      return {
        key: "digital-twin",
        label: "Digital twin",
        tab: "operations",
        state: "ready",
        status: String(digitalTwin.next_gate || "Næste gate"),
        detail: String(digitalTwin.message || "M1–M6 er endnu ikke komplet."),
      };
    }
    return null;
  }

  function render(profile, digitalTwin) {
    const host = document.getElementById("overviewCockpitStages");
    const summary = document.getElementById("overviewCockpitSummary");
    const badge = document.getElementById("overviewCockpitBadge");
    const next = document.getElementById("overviewCockpitNext");
    if (!host || !summary || !badge || !next) return;

    host.replaceChildren();
    next.replaceChildren();

    const bundle = activeBundle(profile);
    const activeBody = bundle?.body_revision || "";
    const activeVoice = bundle?.voice_revision || "";
    const activePersonality = bundle?.personality_revision || "";

    const sourceBound = profile?.source?.kind === "stash-performer" && Boolean(String(profile?.source?.performer_id || "").trim());
    const body = candidateState(profile?.body_revisions, activeBody);
    const voice = candidateState(profile?.voice_revisions, activeVoice);
    const personality = candidateState(profile?.personality_revisions, activePersonality);
    const assembled = Boolean(profile?.active_person_revision);

    const twinReady = digitalTwin?.digital_twin_ready === true && digitalTwin?.production_activation === true;
    const stages = [
      {
        key: "source",
        label: "1 · Source",
        tab: "body",
        state: sourceBound ? "complete" : "missing",
        status: sourceBound ? "Bundet" : "Mangler",
        detail: sourceBound
          ? `${profile.source.performer_name || "Stash performer"} · id ${profile.source.performer_id}`
          : "Ingen authoritative Stash performer-binding.",
      },
      { key: "body", label: "2 · Krop", tab: "body", ...body },
      { key: "voice", label: "3 · Stemme", tab: "voice", ...voice },
      { key: "personality", label: "4 · Personality", tab: "personality", ...personality },
      {
        key: "assemble",
        label: "5 · Person Revision",
        tab: "assemble",
        state: assembled ? "complete" : "missing",
        status: assembled ? "Aktiv" : "Mangler",
        detail: assembled
          ? String(profile.active_person_revision)
          : "Komponenterne er endnu ikke samlet, auditioneret og compatibility-godkendt.",
      },
      {
        key: "digital-twin",
        label: "6 · Digital twin",
        tab: "operations",
        state: twinReady ? "complete" : (assembled ? "ready" : "blocked"),
        status: twinReady ? "M6 klar" : (digitalTwin?.next_gate || (assembled ? "Fortsæt" : "Blokeret")),
        detail: digitalTwin
          ? String(digitalTwin.message || "M1–M6 status tilgængelig i Drift.")
          : "Digital Twin-status kunne ikke bekræftes.",
      },
    ];

    for (const stage of stages) host.appendChild(stageNode(stage));

    const completed = stages.filter((item) => item.state === "complete").length;
    summary.textContent = `${completed}/${stages.length} hovedtrin komplette · ${(profile?.body_revisions || []).length} body · ${(profile?.voice_revisions || []).length} voice · ${(profile?.personality_revisions || []).length} personality kandidater`;
    badge.textContent = twinReady ? "Komplet" : `${completed}/${stages.length}`;
    badge.classList.toggle("muted", !twinReady);

    const action = nextAction(stages, digitalTwin);
    if (!action) {
      const done = document.createElement("div");
      done.className = "person-cockpit-next-copy";
      done.textContent = "Ingen næste person-handling: den aktuelle Person Revision har komplet Digital Twin authority.";
      next.appendChild(done);
      return;
    }

    const copy = document.createElement("div");
    copy.className = "person-cockpit-next-copy";
    const title = document.createElement("strong");
    title.textContent = `Næste: ${action.label}`;
    const detail = document.createElement("div");
    detail.className = "fine-print";
    detail.textContent = action.detail;
    copy.append(title, detail);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "primary";
    button.textContent = action.tab === "operations" ? "Åbn Drift" : `Åbn ${action.label.replace(/^\d+ · /, "")}`;
    button.addEventListener("click", () => document.querySelector(`.tab[data-tab="${action.tab}"]`)?.click());
    next.append(copy, button);
  }

  function reset(message = "Vælg en person for samlet pipeline-status.") {
    const host = document.getElementById("overviewCockpitStages");
    const summary = document.getElementById("overviewCockpitSummary");
    const badge = document.getElementById("overviewCockpitBadge");
    const next = document.getElementById("overviewCockpitNext");
    host?.replaceChildren();
    next?.replaceChildren();
    if (summary) summary.textContent = message;
    if (badge) {
      badge.textContent = "Ukendt";
      badge.classList.add("muted");
    }
  }

  async function refresh() {
    const id = personId();
    const current = ++serial;
    if (!id) return reset();

    const summary = document.getElementById("overviewCockpitSummary");
    if (summary) summary.textContent = "Kontrollerer samlet person-pipeline…";
    try {
      const [profile, twin] = await Promise.all([
        readJson(`/api/v1/people/${encodeURIComponent(id)}`),
        readJson(`/api/v1/people/${encodeURIComponent(id)}/digital-twin-readiness`).catch(() => null),
      ]);
      if (current !== serial || personId() !== id) return;
      render(profile, twin);
    } catch (error) {
      if (current !== serial) return;
      reset(`Person-overblik kunne ikke læses: ${error.message}`);
    }
  }

  const personNode = document.getElementById("personId");
  if (personNode) {
    new MutationObserver(() => void refresh())
      .observe(personNode, { childList: true, characterData: true, subtree: true });
  }
  document.querySelector('.tab[data-tab="overview"]')?.addEventListener("click", () => {
    setTimeout(() => void refresh(), 0);
  });
  setTimeout(() => void refresh(), 800);
})();
