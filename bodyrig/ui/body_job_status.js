(() => {
  const ACTIVE = new Set(["queued", "running"]);
  const FINAL_FAILURE = new Set(["failed", "canceled", "interrupted"]);
  let timer = null;
  let lastPersonId = "";

  function currentPersonId() {
    return (document.getElementById("personId")?.textContent || "").trim();
  }

  function ensureCard() {
    let card = document.getElementById("bodyJobCard");
    if (card) return card;
    const tab = document.getElementById("tab-body");
    if (!tab) return null;
    card = document.createElement("article");
    card.id = "bodyJobCard";
    card.className = "card space-top";
    card.innerHTML = `
      <div class="card-row">
        <div><div class="card-label">Seneste body-build</div><div id="bodyJobSummary" class="muted-text">Ingen jobstatus endnu.</div></div>
        <span id="bodyJobBadge" class="badge muted">Ingen</span>
      </div>
      <div id="bodyJobDetail" class="proposal muted-text">BodyRig viser persisted jobstatus her, også efter browser- eller service-restart.</div>
      <p id="bodyJobSafety" class="fine-print">Et afbrudt fysisk build genstartes aldrig automatisk. Operatøren skal inspicere evidence og starte et nyt build eksplicit.</p>`;
    const revisions = document.getElementById("bodyRevisions")?.closest("article");
    if (revisions) tab.insertBefore(card, revisions);
    else tab.appendChild(card);
    return card;
  }

  function fmt(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("da-DK");
  }

  function label(status) {
    return ({ queued: "I kø", running: "Kører", succeeded: "Færdig", failed: "Fejlet", canceled: "Annulleret", interrupted: "Afbrudt" })[status] || status || "Ukendt";
  }

  function render(job) {
    ensureCard();
    const badge = document.getElementById("bodyJobBadge");
    const summary = document.getElementById("bodyJobSummary");
    const detail = document.getElementById("bodyJobDetail");
    if (!badge || !summary || !detail) return;

    if (!job) {
      badge.textContent = "Ingen";
      badge.classList.add("muted");
      summary.textContent = "Ingen body-build jobs for denne person.";
      detail.textContent = "Når et build startes, vises persisted status, revision og eventuelle fejl her.";
      return;
    }

    badge.textContent = label(job.status);
    badge.classList.toggle("muted", !ACTIVE.has(job.status));
    summary.textContent = `${job.job_id} · oprettet ${fmt(job.created_utc)}`;

    const lines = [
      `Status: ${label(job.status)}`,
      `BodyRig revision: ${job.bodyrig_revision || "—"}`,
      `Start: ${fmt(job.started_utc)}`,
      `Slut: ${fmt(job.completed_utc)}`,
    ];
    if (job.body_revision) lines.push(`Ny body revision: ${job.body_revision}`);
    if (job.canonical_body_id) lines.push(`Canonical body id: ${job.canonical_body_id}`);
    if (job.error) lines.push(`Fejl: ${job.error}`);
    if (job.status === "interrupted") lines.push("Fail-closed: buildet blev ikke genstartet automatisk efter service-restart.");
    detail.textContent = lines.join("\n");
  }

  async function refresh() {
    clearTimeout(timer);
    const personId = currentPersonId();
    if (!personId) {
      render(null);
      timer = setTimeout(refresh, 2000);
      return;
    }
    lastPersonId = personId;
    try {
      const response = await fetch(`/api/v1/jobs?person_id=${encodeURIComponent(personId)}`, { headers: { Accept: "application/json" } });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      if (currentPersonId() !== personId) {
        timer = setTimeout(refresh, 0);
        return;
      }
      const job = Array.isArray(payload.jobs) ? payload.jobs.find((item) => item?.kind === "body-build") || null : null;
      render(job);
      timer = setTimeout(refresh, job && ACTIVE.has(job.status) ? 2000 : 5000);
    } catch (error) {
      ensureCard();
      const badge = document.getElementById("bodyJobBadge");
      const detail = document.getElementById("bodyJobDetail");
      if (badge) {
        badge.textContent = "Statusfejl";
        badge.classList.add("muted");
      }
      if (detail) detail.textContent = `Kunne ikke hente persisted body-jobstatus: ${error.message}`;
      timer = setTimeout(refresh, 5000);
    }
  }

  const personIdNode = document.getElementById("personId");
  if (personIdNode) {
    new MutationObserver(() => {
      const current = currentPersonId();
      if (current !== lastPersonId) {
        clearTimeout(timer);
        void refresh();
      }
    }).observe(personIdNode, { childList: true, characterData: true, subtree: true });
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      clearTimeout(timer);
      void refresh();
    }
  });
  ensureCard();
  void refresh();
})();

(() => {
  const KINDS = [
    ["body", "Krop", "assembleBody", "bodyRevisions"],
    ["voice", "Stemme", "assembleVoice", "voiceRevisions"],
    ["personality", "Personlighed", "assemblePersonality", "personalityRevisions"],
  ];
  let timer = null;
  let requestSerial = 0;
  let currentProfile = null;

  function currentPersonId() {
    return (document.getElementById("personId")?.textContent || "").trim();
  }

  function ensureAlignmentCard() {
    let card = document.getElementById("sourceAlignmentCard");
    if (card) return card;
    const tab = document.getElementById("tab-assemble");
    if (!tab) return null;
    card = document.createElement("article");
    card.id = "sourceAlignmentCard";
    card.className = "card";
    card.innerHTML = `
      <div class="card-row">
        <div>
          <div class="card-label">Source authority</div>
          <div id="sourceAlignmentSummary" class="muted-text">Kontrollerer kildebinding…</div>
        </div>
        <span id="sourceAlignmentBadge" class="badge muted">Kontrollerer</span>
      </div>
      <div id="sourceAlignmentComponents" class="proposal muted-text"></div>
      <p id="sourceAlignmentDetail" class="fine-print">For en Stash-bundet person skal den valgte krop, stemme og personlighed alle være bundet til samme performer før samlet audition.</p>`;
    const firstCard = tab.querySelector(":scope > article.card");
    if (firstCard) tab.insertBefore(card, firstCard);
    else tab.prepend(card);
    const prepare = document.getElementById("prepareAssemblyButton");
    if (prepare) prepare.setAttribute("aria-describedby", "sourceAlignmentDetail");
    return card;
  }

  function statusFor(profile, kind, revisionId) {
    const components = profile?._source_alignment?.components;
    const byRevision = components && typeof components === "object" ? components[kind] : null;
    return revisionId && byRevision && typeof byRevision === "object" ? byRevision[revisionId] || null : null;
  }

  function clearRevisionBadges() {
    document.querySelectorAll(".source-alignment-badge").forEach((node) => node.remove());
  }

  function renderRevisionBadges(profile) {
    clearRevisionBadges();
    if (!profile?.source) return;
    for (const [kind, , , listId] of KINDS) {
      const list = document.getElementById(listId);
      if (!list) continue;
      list.querySelectorAll(".revision-item").forEach((row) => {
        const revisionId = (row.querySelector(".revision-id")?.textContent || "").trim();
        if (!revisionId) return;
        const status = statusFor(profile, kind, revisionId);
        const badge = document.createElement("span");
        badge.className = `badge source-alignment-badge${status?.aligned === true ? "" : " muted"}`;
        badge.textContent = status?.aligned === true ? "Kilde ✓" : "Kilde mangler";
        badge.title = status?.aligned === true
          ? `Verificeret mod ${profile.source.performer_name} · Stash id ${profile.source.performer_id}`
          : String(status?.reason || "Ingen verificeret source-binding for denne revision.");
        row.querySelector(".revision-top")?.appendChild(badge);
      });
    }
  }

  function render(profile) {
    ensureAlignmentCard();
    currentProfile = profile;
    const summary = document.getElementById("sourceAlignmentSummary");
    const badge = document.getElementById("sourceAlignmentBadge");
    const componentsNode = document.getElementById("sourceAlignmentComponents");
    const detail = document.getElementById("sourceAlignmentDetail");
    const prepare = document.getElementById("prepareAssemblyButton");
    if (!summary || !badge || !componentsNode || !detail || !prepare) return;

    renderRevisionBadges(profile);

    if (!profile) {
      summary.textContent = "Ingen person valgt.";
      badge.textContent = "Ingen person";
      badge.classList.add("muted");
      componentsNode.textContent = "";
      detail.textContent = "Vælg en person for at kontrollere source authority.";
      prepare.disabled = false;
      prepare.removeAttribute("title");
      return;
    }

    if (!profile.source) {
      summary.textContent = "Lokal profil uden Stash source authority.";
      badge.textContent = "Draft-mode";
      badge.classList.add("muted");
      componentsNode.textContent = "Source alignment er ikke påkrævet for denne lokale draft-profil.";
      detail.textContent = "En lokal profil kan auditioneres som draft. Stash-bound Person Studio-profiler bruger den strengere source gate.";
      prepare.disabled = false;
      prepare.removeAttribute("title");
      return;
    }

    summary.textContent = `${profile.source.performer_name} · Stash id ${profile.source.performer_id}`;
    const lines = [];
    const blockers = [];
    for (const [kind, label, selectId] of KINDS) {
      const revisionId = document.getElementById(selectId)?.value || "";
      if (!revisionId) {
        lines.push(`${label}: ingen revision valgt`);
        blockers.push(`${label}: vælg en revision`);
        continue;
      }
      const status = statusFor(profile, kind, revisionId);
      if (status?.aligned === true) {
        lines.push(`${label}: ${revisionId} · Kilde ✓ · ${status.evidence_kind || "verificeret evidence"}`);
      } else {
        const reason = String(status?.reason || "source-binding mangler");
        lines.push(`${label}: ${revisionId} · Kilde mangler · ${reason}`);
        blockers.push(`${label} ${revisionId}: ${reason}`);
      }
    }
    componentsNode.textContent = lines.join("\n");

    const ready = blockers.length === 0;
    badge.textContent = ready ? "Kildeklar" : "Låst";
    badge.classList.toggle("muted", !ready);
    prepare.disabled = !ready;
    if (ready) {
      prepare.removeAttribute("title");
      detail.textContent = "Alle tre valgte kandidater er verificeret mod samme Stash performer. Samlet audition er åben.";
    } else {
      const message = `Samlet audition er låst: ${blockers.join(" · ")}`;
      prepare.title = message;
      detail.textContent = message;
    }
  }

  async function refresh() {
    clearTimeout(timer);
    const personId = currentPersonId();
    const serial = ++requestSerial;
    if (!personId) {
      render(null);
      timer = setTimeout(refresh, 3000);
      return;
    }
    try {
      const response = await fetch(`/api/v1/people/${encodeURIComponent(personId)}`, { headers: { Accept: "application/json" }, cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      if (serial !== requestSerial || currentPersonId() !== personId) return;
      render(payload);
    } catch (error) {
      ensureAlignmentCard();
      const summary = document.getElementById("sourceAlignmentSummary");
      const badge = document.getElementById("sourceAlignmentBadge");
      const detail = document.getElementById("sourceAlignmentDetail");
      const prepare = document.getElementById("prepareAssemblyButton");
      if (summary) summary.textContent = "Kunne ikke verificere source alignment.";
      if (badge) {
        badge.textContent = "Statusfejl";
        badge.classList.add("muted");
      }
      if (detail) detail.textContent = `Fail-closed for Stash-bound workflow: ${error.message}`;
      if (prepare) {
        prepare.disabled = true;
        prepare.title = `Source alignment kunne ikke verificeres: ${error.message}`;
      }
    } finally {
      timer = setTimeout(refresh, 5000);
    }
  }

  const personIdNode = document.getElementById("personId");
  if (personIdNode) {
    new MutationObserver(() => {
      clearTimeout(timer);
      void refresh();
    }).observe(personIdNode, { childList: true, characterData: true, subtree: true });
  }
  for (const [, , selectId] of KINDS) {
    document.getElementById(selectId)?.addEventListener("change", () => {
      if (currentProfile && currentProfile.person_id === currentPersonId()) render(currentProfile);
      else void refresh();
    });
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      clearTimeout(timer);
      void refresh();
    }
  });
  ensureAlignmentCard();
  void refresh();
})();

(() => {
  const OPEN = new Set(["uploading", "queued", "running", "needs_speaker", "needs_reference", "cancelling"]);
  const POLL_FAST = new Set(["uploading", "queued", "running", "cancelling"]);
  let timer = null;
  let lastPersonId = "";
  let currentProfile = null;
  let currentJob = null;

  function currentPersonId() {
    return (document.getElementById("personId")?.textContent || "").trim();
  }

  async function apiJson(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: { Accept: "application/json", ...(options.headers || {}) },
      cache: "no-store",
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail || payload));
    return payload;
  }

  function ensureCard() {
    let card = document.getElementById("sourceVoiceBuildCard");
    if (card) return card;
    const tab = document.getElementById("tab-voice");
    if (!tab) return null;
    card = document.createElement("article");
    card.id = "sourceVoiceBuildCard";
    card.className = "card";
    card.innerHTML = `
      <div class="card-row">
        <div>
          <div class="card-label">Source-bound VoiceRig</div>
          <p class="muted-text">Byg stemmen af de samme eksakte Stash-videofiler, som den valgte body revision er bundet til.</p>
        </div>
        <span id="sourceVoiceBadge" class="badge muted">Ikke startet</span>
      </div>
      <div class="field-row">
        <div><label for="sourceVoiceBody">Kilde-body</label><select id="sourceVoiceBody"><option value="">Henter source-bound bodies…</option></select></div>
        <div><label for="sourceVoiceLanguage">Sprog</label><input id="sourceVoiceLanguage" value="da" maxlength="32"></div>
      </div>
      <button id="sourceVoiceStart" class="primary full" disabled>Byg stemme fra samme Stash-kilde</button>
      <div id="sourceVoiceSummary" class="fine-print">Vælg en source-bound body revision.</div>
      <progress id="sourceVoiceProgress" max="100" value="0" class="full"></progress>
      <div id="sourceVoiceChoices" class="revision-list"></div>
      <div id="sourceVoiceResult" class="proposal muted-text"></div>
      <p class="fine-print">Manuelt valgte/importerede VoiceRig-stemmer er fortsat brugbare som drafts, men får ikke source authority og kan derfor ikke godkendes som samme Stash-person.</p>`;
    tab.prepend(card);
    document.getElementById("sourceVoiceStart")?.addEventListener("click", () => void startBuild());
    return card;
  }

  function statusLabel(status) {
    return ({
      uploading: "Uploader",
      queued: "I kø",
      running: "Bygger",
      needs_speaker: "Vælg speaker",
      needs_reference: "Vælg reference",
      cancelling: "Annullerer",
      succeeded: "Kilde ✓",
      failed: "Fejlet",
      canceled: "Annulleret",
      interrupted: "Afbrudt",
    })[status] || status || "Ikke startet";
  }

  function setStartEnabled() {
    const button = document.getElementById("sourceVoiceStart");
    const body = document.getElementById("sourceVoiceBody");
    if (!button || !body) return;
    button.disabled = !currentProfile?.source || !body.value || Boolean(currentJob && OPEN.has(currentJob.status));
  }

  function populateBodies(profile) {
    const select = document.getElementById("sourceVoiceBody");
    if (!select) return;
    const previous = select.value;
    select.innerHTML = "";
    const statuses = profile?._source_alignment?.components?.body || {};
    const bodies = (profile?.body_revisions || []).filter((item) => statuses[item.revision_id]?.aligned === true);
    if (!bodies.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = profile?.source ? "Ingen source-bound body med verificeret evidence" : "Personen har ingen Stash source authority";
      select.appendChild(option);
    } else {
      for (const item of bodies) {
        const option = document.createElement("option");
        option.value = item.revision_id;
        option.textContent = `${item.revision_id} · ${item.body_id} · ${statuses[item.revision_id].evidence_kind || "source evidence"}`;
        select.appendChild(option);
      }
      if (bodies.some((item) => item.revision_id === previous)) select.value = previous;
      else select.value = bodies.at(-1).revision_id;
    }
    const language = document.getElementById("sourceVoiceLanguage");
    if (language && !language.dataset.userEdited) {
      const latestPersonality = (profile?.personality_revisions || []).at(-1);
      language.value = latestPersonality?.default_language || "da";
    }
    select.onchange = setStartEnabled;
    if (language && !language.dataset.wired) {
      language.dataset.wired = "1";
      language.addEventListener("input", () => { language.dataset.userEdited = "1"; });
    }
    setStartEnabled();
  }

  function addAudioChoice(container, choice, kind) {
    const row = document.createElement("div");
    row.className = "revision-item";
    const top = document.createElement("div");
    top.className = "revision-top";
    const text = document.createElement("div");
    const title = document.createElement("div");
    title.className = "revision-id";
    title.textContent = String(choice.label || (kind === "speaker" ? choice.anchor : `Reference ${choice.choice}`));
    const meta = document.createElement("div");
    meta.className = "revision-meta";
    if (kind === "speaker") meta.textContent = `${Number(choice.speech_seconds || 0).toFixed(1)} s tale · ${choice.anchor || ""}`;
    else meta.textContent = `Quality ${choice.quality_score ?? "?"} · ${Number(choice.reference_seconds || 0).toFixed(1)} s reference`;
    text.append(title, meta);
    const button = document.createElement("button");
    button.className = "secondary";
    button.type = "button";
    button.textContent = "Vælg";
    button.addEventListener("click", () => void choose(kind, choice, button));
    top.append(text, button);
    row.appendChild(top);
    if (choice.preview_wav_base64) {
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.preload = "none";
      audio.className = "full";
      audio.src = `data:audio/wav;base64,${choice.preview_wav_base64}`;
      row.appendChild(audio);
    }
    container.appendChild(row);
  }

  function renderChoices(job) {
    const target = document.getElementById("sourceVoiceChoices");
    if (!target) return;
    target.innerHTML = "";
    if (job?.status === "needs_speaker" && Array.isArray(job.speaker_choices)) {
      for (const choice of job.speaker_choices) addAudioChoice(target, choice, "speaker");
    } else if (job?.status === "needs_reference" && Array.isArray(job.reference_choices)) {
      for (const choice of job.reference_choices) addAudioChoice(target, choice, "reference");
    }
  }

  function renderJob(job) {
    currentJob = job || null;
    const badge = document.getElementById("sourceVoiceBadge");
    const summary = document.getElementById("sourceVoiceSummary");
    const progress = document.getElementById("sourceVoiceProgress");
    const result = document.getElementById("sourceVoiceResult");
    if (!badge || !summary || !progress || !result) return;
    if (!job) {
      badge.textContent = "Ikke startet";
      badge.classList.add("muted");
      summary.textContent = "Ingen source-derived VoiceRig-job for denne person endnu.";
      progress.value = 0;
      result.textContent = "";
      renderChoices(null);
      setStartEnabled();
      return;
    }
    badge.textContent = statusLabel(job.status);
    badge.classList.toggle("muted", job.status !== "succeeded");
    progress.value = Number.isFinite(Number(job.progress)) ? Math.max(0, Math.min(100, Number(job.progress))) : 0;
    summary.textContent = `${job.body_revision || "?"} · ${job.stage || job.status} · ${job.message || ""}`;
    renderChoices(job);
    if (job.status === "succeeded") {
      result.innerHTML = "";
      const text = document.createElement("div");
      text.textContent = `${job.voice_revision} · ${job.voice_package} · source-binding ${String(job.source_binding_sha256 || "").slice(0, 16)}…`;
      const reload = document.createElement("button");
      reload.type = "button";
      reload.className = "secondary";
      reload.textContent = "Indlæs den nye voice-kandidat i Person Studio";
      reload.addEventListener("click", () => location.reload());
      result.append(text, reload);
    } else if (["failed", "canceled", "interrupted"].includes(job.status)) {
      result.textContent = job.error ? `Fail-closed: ${job.error}` : statusLabel(job.status);
    } else {
      result.textContent = `VoiceRig job ${job.voicerig_job_id || "oprettes"} · source manifest ${String(job.source_manifest_sha256 || "").slice(0, 16)}…`;
    }
    setStartEnabled();
  }

  async function choose(kind, choice, button) {
    if (!currentJob) return;
    button.disabled = true;
    try {
      const suffix = kind === "speaker"
        ? `/speaker?anchor=${encodeURIComponent(choice.anchor)}`
        : `/reference?choice=${encodeURIComponent(choice.choice)}`;
      const job = await apiJson(`/api/v1/jobs/${encodeURIComponent(currentJob.job_id)}${suffix}`, { method: "POST" });
      renderJob(job);
      schedule();
    } catch (error) {
      const result = document.getElementById("sourceVoiceResult");
      if (result) result.textContent = `Valget blev afvist: ${error.message}`;
      button.disabled = false;
    }
  }

  async function startBuild() {
    const personId = currentPersonId();
    const body = document.getElementById("sourceVoiceBody")?.value || "";
    const language = (document.getElementById("sourceVoiceLanguage")?.value || "da").trim();
    if (!personId || !body) return;
    const button = document.getElementById("sourceVoiceStart");
    if (button) button.disabled = true;
    try {
      const job = await apiJson(
        `/api/v1/people/${encodeURIComponent(personId)}/voice/build-from-source?body_revision=${encodeURIComponent(body)}&language=${encodeURIComponent(language)}`,
        { method: "POST" },
      );
      renderJob(job);
      schedule();
    } catch (error) {
      const result = document.getElementById("sourceVoiceResult");
      if (result) result.textContent = `Source voice-build kunne ikke startes: ${error.message}`;
      currentJob = null;
      setStartEnabled();
    }
  }

  function schedule() {
    clearTimeout(timer);
    const delay = currentJob && POLL_FAST.has(currentJob.status) ? 2000 : currentJob && OPEN.has(currentJob.status) ? 5000 : 8000;
    timer = setTimeout(() => void refresh(), delay);
  }

  async function refresh() {
    clearTimeout(timer);
    ensureCard();
    const personId = currentPersonId();
    lastPersonId = personId;
    if (!personId) {
      currentProfile = null;
      renderJob(null);
      schedule();
      return;
    }
    try {
      const [profile, jobsPayload] = await Promise.all([
        apiJson(`/api/v1/people/${encodeURIComponent(personId)}`),
        apiJson(`/api/v1/jobs?person_id=${encodeURIComponent(personId)}`),
      ]);
      if (currentPersonId() !== personId) return void refresh();
      currentProfile = profile;
      populateBodies(profile);
      let job = Array.isArray(jobsPayload.jobs) ? jobsPayload.jobs.find((item) => item?.kind === "voice-build") || null : null;
      if (job && OPEN.has(job.status)) job = await apiJson(`/api/v1/jobs/${encodeURIComponent(job.job_id)}`);
      if (currentPersonId() !== personId) return void refresh();
      renderJob(job);
    } catch (error) {
      const badge = document.getElementById("sourceVoiceBadge");
      const result = document.getElementById("sourceVoiceResult");
      if (badge) {
        badge.textContent = "Statusfejl";
        badge.classList.add("muted");
      }
      if (result) result.textContent = `Kunne ikke verificere source voice-status: ${error.message}`;
      currentJob = { status: "running" };
      setStartEnabled();
    } finally {
      schedule();
    }
  }

  const personIdNode = document.getElementById("personId");
  if (personIdNode) {
    new MutationObserver(() => {
      const personId = currentPersonId();
      if (personId !== lastPersonId) {
        clearTimeout(timer);
        currentJob = null;
        currentProfile = null;
        void refresh();
      }
    }).observe(personIdNode, { childList: true, characterData: true, subtree: true });
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      clearTimeout(timer);
      void refresh();
    }
  });
  ensureCard();
  void refresh();
})();
