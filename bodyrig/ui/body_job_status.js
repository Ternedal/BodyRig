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
      const job = Array.isArray(payload.jobs) && payload.jobs.length ? payload.jobs[0] : null;
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
