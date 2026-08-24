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
