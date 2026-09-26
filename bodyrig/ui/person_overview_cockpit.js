(() => {
  let serial = 0;
  const OPEN_JOB_STATES = new Set(["uploading", "queued", "running", "needs_speaker", "needs_reference", "cancelling"]);
  const ACTION_JOB_STATES = new Set(["needs_speaker", "needs_reference"]);

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

  async function safeReadJson(url) {
    try {
      return { ok: true, value: await readJson(url) };
    } catch (error) {
      return { ok: false, error: error.message };
    }
  }

  function activeBundle(profile) {
    const id = String(profile?.active_person_revision || "");
    if (!id) return null;
    return (Array.isArray(profile?.person_revisions) ? profile.person_revisions : [])
      .find((item) => String(item?.revision_id || "") === id) || null;
  }

  function sourceBound(profile) {
    return profile?.source?.kind === "stash-performer"
      && Boolean(String(profile?.source?.performer_id || "").trim());
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

  function stageSatisfiesPipeline(stage) {
    if (!stage) return false;
    if (stage.key === "body" || stage.key === "voice" || stage.key === "personality") {
      return stage.state === "ready" || stage.state === "complete";
    }
    return stage.state === "complete";
  }

  async function authoritativePersonJobs(id) {
    const listing = await safeReadJson(`/api/v1/jobs?person_id=${encodeURIComponent(id)}`);
    if (!listing.ok) return { jobs: [], monitoring_error: listing.error };
    const jobs = Array.isArray(listing.value?.jobs) ? listing.value.jobs : [];
    const hydrated = await Promise.all(
      jobs.map(async (job) => {
        const status = String(job?.status || "");
        const jobId = String(job?.job_id || "");
        if (
          String(job?.kind || "") !== "voice-build"
          || !OPEN_JOB_STATES.has(status)
          || !jobId
        ) {
          return job;
        }
        const detail = await safeReadJson(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
        if (detail.ok) return detail.value;
        return {
          ...job,
          monitoring_error: `VoiceRig job-status kunne ikke bekræftes: ${detail.error}`,
        };
      })
    );
    return { jobs: hydrated, monitoring_error: null };
  }

  async function photorealStatus(profile, id) {
    if (!sourceBound(profile)) return { ok: true, value: null };
    return safeReadJson(
      `/api/v1/people/${encodeURIComponent(id)}/body/photoreal-control-plane`
    );
  }

  function latestJobPerKind(jobs) {
    const latest = new Map();
    for (const job of jobs) {
      const kind = String(job?.kind || "job");
      const stamp = String(job?.created_utc || job?.started_utc || job?.completed_utc || "");
      const previous = latest.get(kind);
      if (!previous || stamp > previous.stamp) latest.set(kind, { stamp, job });
    }
    return [...latest.values()].map((item) => item.job);
  }

  function operatorAttention(profile, jobsRead, photorealRead, twinRead) {
    const items = [];
    const add = (priority, severity, label, detail, tab, buttonLabel) => {
      items.push({ priority, severity, label, detail, tab, buttonLabel });
    };

    if (jobsRead?.monitoring_error) {
      add(
        100,
        "blocked",
        "Job-status kan ikke bekræftes",
        String(jobsRead.monitoring_error),
        "operations",
        "Åbn Drift"
      );
    }

    const jobs = Array.isArray(jobsRead?.jobs) ? jobsRead.jobs : [];
    for (const job of jobs) {
      if (job?.monitoring_error) {
        add(
          100,
          "blocked",
          "VoiceRig-status kan ikke bekræftes",
          String(job.monitoring_error),
          "voice",
          "Åbn Stemme"
        );
        continue;
      }
      const status = String(job?.status || "");
      if (!ACTION_JOB_STATES.has(status)) continue;
      add(
        100,
        "action",
        status === "needs_speaker" ? "Stemme kræver speaker-valg" : "Stemme kræver reference-valg",
        String(job?.message || job?.job_id || "VoiceRig venter på operator-input."),
        "voice",
        "Åbn Stemme"
      );
    }

    for (const job of latestJobPerKind(jobs)) {
      const status = String(job?.status || "");
      if (!["failed", "interrupted"].includes(status)) continue;
      const kind = String(job?.kind || "job");
      add(
        70,
        "blocked",
        kind === "voice-build" ? "Seneste voice-build fejlede" : "Seneste body-build fejlede",
        String(job?.error || job?.message || job?.job_id || "Seneste job kræver eftersyn."),
        kind === "voice-build" ? "voice" : "body",
        kind === "voice-build" ? "Åbn Stemme" : "Åbn Krop"
      );
    }

    if (photorealRead?.ok === false) {
      add(
        95,
        "blocked",
        "Photoreal-status kan ikke bekræftes",
        String(photorealRead.error || "Photoreal monitoring fejlede."),
        "body",
        "Åbn Krop"
      );
    } else {
      const value = photorealRead?.value;
      if (value && typeof value === "object") {
        const stalled = value.exavatar?.activity?.stalled_suspected === true;
        const busy = value.exavatar?.busy === true;
        const state = String(value.state || "unknown");
        const gate = String(value.pipeline?.next_gate || "").trim();
        const reason = String(
          value.exavatar?.activity?.reason
          || value.pipeline?.message
          || "Photoreal kræver operator-opmærksomhed."
        );
        if (stalled) {
          add(
            95,
            "blocked",
            "ExAvatar kan være stalled",
            [gate ? `Gate: ${gate}` : "", reason].filter(Boolean).join(" · "),
            "body",
            "Åbn Krop"
          );
        } else if (!busy && state === "blocked") {
          add(
            90,
            "blocked",
            "Photoreal er blokeret",
            [gate ? `Gate: ${gate}` : "", reason].filter(Boolean).join(" · "),
            "body",
            "Åbn Krop"
          );
        } else if (!busy && ["required", "human-review-required", "operator-input-required"].includes(state)) {
          add(
            85,
            "action",
            state === "human-review-required" ? "Photoreal kræver human review" : "Photoreal har et næste trin",
            [gate ? `Gate: ${gate}` : "", reason].filter(Boolean).join(" · "),
            "body",
            "Åbn Krop"
          );
        }
      }
    }

    const twin = twinRead?.ok === true ? twinRead.value : null;
    const assembled = Boolean(String(profile?.active_person_revision || ""));
    if (twinRead?.ok === false && assembled) {
      add(
        80,
        "blocked",
        "Digital-twin status kan ikke bekræftes",
        String(twinRead.error || "M1–M6 monitoring fejlede."),
        "operations",
        "Åbn Drift"
      );
    } else if (
      assembled
      && twin
      && !(twin.digital_twin_ready === true && twin.production_activation === true)
    ) {
      add(
        60,
        String(twin.state || "") === "blocked" ? "blocked" : "action",
        "Digital twin er ikke komplet",
        [
          twin.next_gate ? `Næste gate: ${twin.next_gate}` : "",
          String(twin.message || ""),
        ].filter(Boolean).join(" · ") || "M1–M6 kræver fortsat arbejde.",
        "operations",
        "Åbn Drift"
      );
    }

    return items
      .sort((a, b) => b.priority - a.priority)
      .slice(0, 6);
  }

  function renderAttention(items) {
    const host = document.getElementById("overviewCockpitAttention");
    if (!host) return;
    host.replaceChildren();
    const list = Array.isArray(items) ? items : [];
    if (!list.length) {
      host.classList.add("hidden");
      return;
    }
    host.classList.remove("hidden");

    const header = document.createElement("div");
    header.className = "person-cockpit-attention-head";
    const title = document.createElement("strong");
    title.textContent = "Aktuel operator-opmærksomhed";
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = String(list.length);
    header.append(title, badge);
    host.appendChild(header);

    for (const item of list.slice(0, 3)) {
      const row = document.createElement("div");
      row.className = `person-cockpit-attention-item ${item.severity}`;
      const copy = document.createElement("div");
      copy.className = "person-cockpit-attention-copy";
      const itemTitle = document.createElement("strong");
      itemTitle.textContent = item.label;
      const detail = document.createElement("div");
      detail.className = "fine-print";
      detail.textContent = item.detail;
      copy.append(itemTitle, detail);

      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.textContent = item.buttonLabel || "Åbn";
      button.addEventListener("click", () => {
        document.querySelector(`.tab[data-tab="${item.tab}"]`)?.click();
      });
      row.append(copy, button);
      host.appendChild(row);
    }
  }

  function nextAction(stages, digitalTwin, attentionItems) {
    const urgent = (Array.isArray(attentionItems) ? attentionItems : [])
      .find((item) => Number(item?.priority || 0) >= 80);
    if (urgent) {
      return {
        key: "operator-attention",
        label: urgent.label,
        tab: urgent.tab,
        state: urgent.severity,
        status: "Kræver handling",
        detail: urgent.detail,
        buttonLabel: urgent.buttonLabel,
      };
    }

    const ordered = ["source", "body", "voice", "personality", "assemble"];
    for (const key of ordered) {
      const stage = stages.find((item) => item.key === key);
      if (stage && !stageSatisfiesPipeline(stage)) return stage;
    }
    if (digitalTwin && digitalTwin.digital_twin_ready !== true) {
      return {
        key: "digital-twin",
        label: "Digital twin",
        tab: "operations",
        state: "ready",
        status: String(digitalTwin.next_gate || "Næste gate"),
        detail: String(digitalTwin.message || "M1–M6 er endnu ikke komplet."),
        buttonLabel: "Åbn Drift",
      };
    }
    return null;
  }

  function publishHudState({ profile, bundle, pipelineSatisfied, pipelineTotal }) {
    const hud = document.getElementById("personHud");
    if (!hud) return;

    const revision = String(profile?.active_person_revision || "").trim();
    const personName = String(profile?.name || "").trim();
    const bodyRevision = String(bundle?.body_revision || "").trim();
    const voiceRevision = String(bundle?.voice_revision || "").trim();
    const personalityRevision = String(bundle?.personality_revision || "").trim();
    const complete = Number(pipelineSatisfied);
    const total = Number(pipelineTotal);

    if (
      !Number.isInteger(complete)
      || !Number.isInteger(total)
      || total <= 0
      || complete < 0
      || complete > total
    ) {
      publishHudUnknown();
      return;
    }

    hud.dataset.stateVersion = "1";
    hud.dataset.personName = personName;
    hud.dataset.personRevision = revision;
    hud.dataset.pipelineComplete = String(complete);
    hud.dataset.pipelineTotal = String(total);
    hud.dataset.bodyState = bodyRevision ? "bound" : "unbound";
    hud.dataset.voiceState = voiceRevision ? "bound" : "unbound";
    hud.dataset.personalityState = personalityRevision ? "bound" : "unbound";
  }

  function publishHudUnknown() {
    const hud = document.getElementById("personHud");
    if (!hud) return;
    hud.dataset.stateVersion = "1";
    hud.dataset.personName = "";
    hud.dataset.personRevision = "";
    hud.dataset.pipelineComplete = "0";
    hud.dataset.pipelineTotal = "0";
    hud.dataset.bodyState = "unknown";
    hud.dataset.voiceState = "unknown";
    hud.dataset.personalityState = "unknown";
  }

  function publishTopologyState(profile, bundle, digitalTwin) {
    const root = document.querySelector(".person-topology-card");
    if (!root) return;

    const source = profile?.source?.kind === "stash-performer"
      ? String(profile?.source?.performer_name || profile?.source?.performer_id || "").trim()
      : "";
    const revision = String(profile?.active_person_revision || "").trim();
    const body = String(bundle?.body_revision || "").trim();
    const voice = String(bundle?.voice_revision || "").trim();
    const personality = String(bundle?.personality_revision || "").trim();
    const twinReady = Boolean(
      revision
      && digitalTwin?.digital_twin_ready === true
      && digitalTwin?.production_activation === true
    );
    const twinDetail = String(
      digitalTwin?.message
      || digitalTwin?.next_gate
      || (twinReady ? "M6 klar" : "Digital Twin-status ukendt")
    ).slice(0, 500);

    root.dataset.stateVersion = "1";
    root.dataset.sourceState = source ? "bound" : "unbound";
    root.dataset.sourceLabel = source;
    root.dataset.bodyState = body ? "bound" : "unbound";
    root.dataset.bodyLabel = body;
    root.dataset.voiceState = voice ? "bound" : "unbound";
    root.dataset.voiceLabel = voice;
    root.dataset.personalityState = personality ? "bound" : "unbound";
    root.dataset.personalityLabel = personality;
    root.dataset.coreState = revision && bundle ? "bound" : (revision ? "invalid" : "unbound");
    root.dataset.coreLabel = revision;
    root.dataset.twinState = twinReady ? "ready" : "not-ready";
    root.dataset.twinLabel = twinDetail;
  }

  function publishTopologyUnknown() {
    const root = document.querySelector(".person-topology-card");
    if (!root) return;
    root.dataset.stateVersion = "1";
    root.dataset.sourceState = "unknown";
    root.dataset.sourceLabel = "";
    root.dataset.bodyState = "unknown";
    root.dataset.bodyLabel = "";
    root.dataset.voiceState = "unknown";
    root.dataset.voiceLabel = "";
    root.dataset.personalityState = "unknown";
    root.dataset.personalityLabel = "";
    root.dataset.coreState = "unknown";
    root.dataset.coreLabel = "";
    root.dataset.twinState = "unknown";
    root.dataset.twinLabel = "";
  }

  function publishOverviewControlState({ profile, bundle, pipelineSatisfied, pipelineTotal, twinReady, digitalTwin, action }) {
    const root = document.getElementById("overviewControlStrip");
    if (!root) return;

    const revision = String(profile?.active_person_revision || "").trim();
    const revisionState = revision && bundle ? "bound" : (revision ? "invalid" : "unbound");
    const pipelineState = twinReady ? "complete" : "incomplete";
    const twinState = twinReady
      ? "ready"
      : (digitalTwin && typeof digitalTwin === "object" ? "not-ready" : "unknown");
    const nextLabel = action
      ? [String(action.label || "").trim(), String(action.detail || "").trim()].filter(Boolean).join(" · ")
      : "Ingen prioriteret handling · Person-pipeline og Digital Twin er komplette.";

    root.dataset.stateVersion = "1";
    root.dataset.pipelineState = pipelineState;
    root.dataset.pipelineLabel = twinReady ? "Komplet" : `${pipelineSatisfied}/${pipelineTotal}`;
    root.dataset.revisionState = revisionState;
    root.dataset.revisionLabel = revision || "Ingen aktiv";
    root.dataset.twinState = twinState;
    root.dataset.twinLabel = twinReady
      ? "M6 klar"
      : String(digitalTwin?.next_gate || digitalTwin?.message || "Ukendt").slice(0, 240);
    root.dataset.nextLabel = nextLabel.slice(0, 1000);
  }

  function publishOverviewControlUnknown() {
    const root = document.getElementById("overviewControlStrip");
    if (!root) return;
    root.dataset.stateVersion = "1";
    root.dataset.pipelineState = "unknown";
    root.dataset.pipelineLabel = "Ukendt";
    root.dataset.revisionState = "unknown";
    root.dataset.revisionLabel = "Ukendt";
    root.dataset.twinState = "unknown";
    root.dataset.twinLabel = "Ukendt";
    root.dataset.nextLabel = "Afventer autoritativt Overview-snapshot…";
  }

  function publishMissionControlState(action) {
    const root = document.getElementById("personMissionControl");
    if (!root) return;

    root.dataset.stateVersion = "1";
    if (!action) {
      root.dataset.missionKind = "complete";
      root.dataset.missionTitle = "Pipeline komplet";
      root.dataset.missionDetail = "Ingen næste person-handling: den aktuelle Person Revision har komplet Digital Twin authority.";
      root.dataset.missionTargetTab = "";
      root.dataset.missionActionLabel = "";
      return;
    }

    const targetTab = String(action.tab || "").trim();
    const allowedTabs = new Set(["overview", "body", "voice", "personality", "assemble", "history", "operations"]);
    if (!allowedTabs.has(targetTab)) {
      publishMissionControlUnknown();
      return;
    }

    const isAttention = action.key === "operator-attention";
    root.dataset.missionKind = isAttention ? "attention" : "next";
    root.dataset.missionTitle = isAttention ? "Kræver handling" : "Næste handling";
    root.dataset.missionDetail = String(action.detail || action.label || "").slice(0, 1000);
    root.dataset.missionTargetTab = targetTab;
    root.dataset.missionActionLabel = String(
      action.buttonLabel
      || (targetTab === "operations" ? "Åbn Drift" : "Åbn relevant kontrol")
    ).slice(0, 120);
  }

  function publishMissionControlUnknown() {
    const root = document.getElementById("personMissionControl");
    if (!root) return;
    root.dataset.stateVersion = "1";
    root.dataset.missionKind = "unknown";
    root.dataset.missionTitle = "Afventer pipeline-status";
    root.dataset.missionDetail = "Mission Control afventer et autoritativt Overview-snapshot.";
    root.dataset.missionTargetTab = "";
    root.dataset.missionActionLabel = "";
  }

  function render(profile, twinRead, jobsRead, photorealRead) {
    const host = document.getElementById("overviewCockpitStages");
    const summary = document.getElementById("overviewCockpitSummary");
    const badge = document.getElementById("overviewCockpitBadge");
    const next = document.getElementById("overviewCockpitNext");
    if (!host || !summary || !badge || !next) return;

    host.replaceChildren();
    next.replaceChildren();

    const digitalTwin = twinRead?.ok === true ? twinRead.value : null;
    const attentionItems = operatorAttention(profile, jobsRead, photorealRead, twinRead);
    renderAttention(attentionItems);

    const bundle = activeBundle(profile);
    const activeBody = bundle?.body_revision || "";
    const activeVoice = bundle?.voice_revision || "";
    const activePersonality = bundle?.personality_revision || "";

    const bound = sourceBound(profile);
    const body = candidateState(profile?.body_revisions, activeBody);
    const voice = candidateState(profile?.voice_revisions, activeVoice);
    const personality = candidateState(profile?.personality_revisions, activePersonality);
    const requestedPersonRevision = String(profile?.active_person_revision || "");
    const assembled = Boolean(requestedPersonRevision && bundle);
    const assemblyInconsistent = Boolean(requestedPersonRevision && !bundle);

    const twinReady = assembled
      && digitalTwin?.digital_twin_ready === true
      && digitalTwin?.production_activation === true;
    publishTopologyState(profile, bundle, digitalTwin);
    const stages = [
      {
        key: "source",
        label: "1 · Source",
        tab: "body",
        state: bound ? "complete" : "missing",
        status: bound ? "Bundet" : "Mangler",
        detail: bound
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
        state: assembled ? "complete" : (assemblyInconsistent ? "blocked" : "missing"),
        status: assembled ? "Aktiv" : (assemblyInconsistent ? "Ugyldig binding" : "Mangler"),
        detail: assembled
          ? requestedPersonRevision
          : (assemblyInconsistent
              ? `Profilen peger på ${requestedPersonRevision}, men revisionen findes ikke i person_revisions.`
              : "Komponenterne er endnu ikke samlet, auditioneret og compatibility-godkendt."),
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
    const pipelineSatisfied = stages.filter((item) => stageSatisfiesPipeline(item)).length;
    summary.textContent = `${pipelineSatisfied}/${stages.length} pipeline-trin klar · ${completed}/${stages.length} aktive/komplette · ${attentionItems.length} aktuelle operator-punkter · ${(profile?.body_revisions || []).length} body · ${(profile?.voice_revisions || []).length} voice · ${(profile?.personality_revisions || []).length} personality kandidater`;
    badge.textContent = twinReady ? "Komplet" : `${pipelineSatisfied}/${stages.length}`;
    badge.classList.toggle("muted", !twinReady);

    publishHudState({
      profile,
      bundle,
      pipelineSatisfied,
      pipelineTotal: stages.length,
    });

    const action = nextAction(stages, digitalTwin, attentionItems);
    publishOverviewControlState({
      profile,
      bundle,
      pipelineSatisfied,
      pipelineTotal: stages.length,
      twinReady,
      digitalTwin,
      action,
    });
    publishMissionControlState(action);
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
    button.textContent = action.buttonLabel
      || (action.tab === "operations" ? "Åbn Drift" : `Åbn ${action.label.replace(/^\d+ · /, "")}`);
    button.addEventListener("click", () => document.querySelector(`.tab[data-tab="${action.tab}"]`)?.click());
    next.append(copy, button);
  }

  function reset(message = "Vælg en person for samlet pipeline-status.") {
    const host = document.getElementById("overviewCockpitStages");
    const summary = document.getElementById("overviewCockpitSummary");
    const badge = document.getElementById("overviewCockpitBadge");
    const next = document.getElementById("overviewCockpitNext");
    const attention = document.getElementById("overviewCockpitAttention");
    host?.replaceChildren();
    next?.replaceChildren();
    attention?.replaceChildren();
    attention?.classList.add("hidden");
    if (summary) summary.textContent = message;
    if (badge) {
      badge.textContent = "Ukendt";
      badge.classList.add("muted");
    }
    publishHudUnknown();
    publishOverviewControlUnknown();
    publishMissionControlUnknown();
    publishTopologyUnknown();
  }

  async function refresh() {
    const id = personId();
    const current = ++serial;
    if (!id) return reset();

    const summary = document.getElementById("overviewCockpitSummary");
    if (summary) summary.textContent = "Kontrollerer samlet person-pipeline…";
    try {
      const profilePromise = readJson(`/api/v1/people/${encodeURIComponent(id)}`);
      const twinPromise = safeReadJson(
        `/api/v1/people/${encodeURIComponent(id)}/digital-twin-readiness`
      );
      const jobsPromise = authoritativePersonJobs(id);
      const profile = await profilePromise;
      const photorealPromise = photorealStatus(profile, id);
      const [twinRead, jobsRead, photorealRead] = await Promise.all([
        twinPromise,
        jobsPromise,
        photorealPromise,
      ]);
      if (current !== serial || personId() !== id) return;
      render(profile, twinRead, jobsRead, photorealRead);
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
