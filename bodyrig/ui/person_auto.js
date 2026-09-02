(() => {
  const $ = (id) => document.getElementById(id);
  const OPEN = new Set(["uploading", "queued", "running", "needs_speaker", "needs_reference", "cancelling"]);
  const FAIL = new Set(["failed", "canceled", "interrupted"]);
  let timer = null;

  async function request(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body !== undefined && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    const response = await fetch(path, { ...options, headers, cache: "no-store" });
    const type = response.headers.get("content-type") || "";
    const payload = type.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? (payload.detail || JSON.stringify(payload)) : payload;
      throw new Error(detail || `HTTP ${response.status}`);
    }
    return payload;
  }

  function personId() {
    return ($("personId")?.textContent || "").trim();
  }

  function workflowKey(id) {
    return `bodyrig-person-auto-v1:${id}`;
  }

  function loadWorkflow(id) {
    if (!id) return null;
    try {
      const value = JSON.parse(localStorage.getItem(workflowKey(id)) || "null");
      return value && value.version === 1 && value.person_id === id ? value : null;
    } catch {
      return null;
    }
  }

  function saveWorkflow(value) {
    localStorage.setItem(workflowKey(value.person_id), JSON.stringify(value));
  }

  function clearWorkflow(id) {
    if (id) localStorage.removeItem(workflowKey(id));
  }

  function setStatus(text, failed = false) {
    const status = $("autoPersonBuildStatus");
    if (!status) return;
    status.textContent = text;
    status.classList.toggle("error", failed);
  }

  function ensureUi() {
    const voiceSplit = document.querySelector("#tab-voice .split");
    const legacyVoice = voiceSplit?.querySelector("article.card");
    if (legacyVoice) legacyVoice.hidden = true;

    const personalitySplit = document.querySelector("#tab-personality .split");
    const legacyPersonality = personalitySplit?.querySelector("article.card");
    if (legacyPersonality) legacyPersonality.hidden = true;

    if (!$("autoPersonalityCard") && personalitySplit && legacyPersonality) {
      const card = document.createElement("article");
      card.className = "card";
      card.id = "autoPersonalityCard";
      card.innerHTML = `
        <div class="card-label">Automatisk personality</div>
        <p class="muted-text">BodyRig bruger captions/transcript fra de samme verificerede Stash-kilder som speaking-style evidence. Findes der ingen tekst-evidence, bruges en neutral fallback i stedet for at gætte personlighed eller biografi.</p>
        <div id="autoPersonalityStatus" class="proposal muted-text">Venter på source-bound body.</div>`;
      personalitySplit.insertBefore(card, legacyPersonality);
    }

    const overview = $("tab-overview");
    if (overview && !$("autoPersonBuildCard")) {
      const card = document.createElement("article");
      card.className = "card space-top";
      card.id = "autoPersonBuildCard";
      card.innerHTML = `
        <div class="card-row">
          <div>
            <div class="card-label">Automatisk person-build</div>
            <p class="muted-text">Én source authority: Stash → krop → VoiceRig-stemme → source-derived personality. Komponenterne bliver stadig først aktive efter samlet audition/review.</p>
          </div>
          <span class="badge">AUTO</span>
        </div>
        <button id="autoPersonBuildButton" class="primary full">Byg hele personen fra Stash</button>
        <div id="autoPersonBuildStatus" class="proposal muted-text">Klar når personen er bundet til Stash.</div>
        <p class="fine-print">Et fysisk body-build genstartes aldrig skjult efter et crash. Hvis VoiceRig ikke kan afgøre speaker/reference sikkert, stopper automatikken ved det ene nødvendige review-valg og fortsætter bagefter.</p>`;
      overview.appendChild(card);
      $("autoPersonBuildButton").addEventListener("click", () => void startFullBuild());
    }

    const bodyButton = $("buildBodyButton");
    if (bodyButton) bodyButton.textContent = "Byg kun ny body-kandidat (avanceret)";
  }

  async function startFullBuild() {
    const id = personId();
    const button = $("autoPersonBuildButton");
    if (!id) return;
    if (button) button.disabled = true;
    try {
      const profile = await request(`/api/v1/people/${encodeURIComponent(id)}`);
      if (!profile.source) throw new Error("Personen skal være bundet til en Stash performer først.");
      const existing = loadWorkflow(id);
      if (existing && existing.state !== "complete" && existing.state !== "failed") {
        setStatus("Der findes allerede et automatisk person-build. Fortsætter det eksisterende flow …");
        return void schedule(0);
      }
      setStatus(`Starter fysisk body-build fra ${profile.source.performer_name} …`);
      const bodyJob = await request(`/api/v1/people/${encodeURIComponent(id)}/body/build`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      saveWorkflow({
        version: 1,
        person_id: id,
        performer_id: String(profile.source.performer_id),
        started_utc: new Date().toISOString(),
        state: "body",
        body_job_id: bodyJob.job_id,
        body_revision: null,
        personality_revision: null,
        personality_transcript_count: null,
        personality_style_exemplar_count: null,
        voice_job_id: null,
        voice_revision: null,
      });
      schedule(0);
    } catch (error) {
      setStatus(error.message, true);
      if (button) button.disabled = false;
    }
  }

  function matchingAutomaticPersonality(profile, bodyRevision) {
    const feedback = `Automatic source-derived personality from ${bodyRevision}`;
    const aligned = profile?._source_alignment?.components?.personality || {};
    return [...(profile?.personality_revisions || [])]
      .reverse()
      .find((item) => item.feedback === feedback && aligned[item.revision_id]?.aligned === true) || null;
  }

  async function ensurePersonality(workflow, profile) {
    if (workflow.personality_revision) return workflow;
    const existing = matchingAutomaticPersonality(profile, workflow.body_revision);
    if (existing) {
      workflow.personality_revision = existing.revision_id;
      saveWorkflow(workflow);
      return workflow;
    }

    setStatus(`Krop ${workflow.body_revision} er klar. Udleder speaking-style/personality fra de samme Stash-kilder …`);
    const result = await request(
      `/api/v1/people/${encodeURIComponent(workflow.person_id)}/personality/build-from-source?body_revision=${encodeURIComponent(workflow.body_revision)}&language=en`,
      { method: "POST" },
    );
    workflow.personality_revision = result.personality_revision;
    workflow.personality_transcript_count = Number(result.transcript_count || 0);
    workflow.personality_style_exemplar_count = Number(result.style_exemplar_count || 0);
    saveWorkflow(workflow);

    const personalityStatus = $("autoPersonalityStatus");
    if (personalityStatus) {
      personalityStatus.textContent = workflow.personality_transcript_count > 0
        ? `${workflow.personality_revision}: ${workflow.personality_transcript_count} transcript/caption-kilder · ${workflow.personality_style_exemplar_count} style-exemplars.`
        : `${workflow.personality_revision}: ingen transcript/caption-evidence; neutral source-bound fallback uden gættet biografi eller indre personlighed.`;
    }
    return workflow;
  }

  function voiceJobForBody(jobs, bodyRevision) {
    return [...jobs]
      .filter((item) => item?.kind === "voice-build" && item.body_revision === bodyRevision)
      .sort((a, b) => String(b.created_utc || "").localeCompare(String(a.created_utc || "")))[0] || null;
  }

  async function ensureVoice(workflow, jobs) {
    if (workflow.voice_revision) return workflow;
    let job = workflow.voice_job_id
      ? await request(`/api/v1/jobs/${encodeURIComponent(workflow.voice_job_id)}`)
      : voiceJobForBody(jobs, workflow.body_revision);

    if (!job) {
      setStatus(`Personality ${workflow.personality_revision} er klar. Starter VoiceRig fra de samme Stash-kilder …`);
      job = await request(
        `/api/v1/people/${encodeURIComponent(workflow.person_id)}/voice/build-from-source?body_revision=${encodeURIComponent(workflow.body_revision)}&language=en`,
        { method: "POST" },
      );
    }
    workflow.voice_job_id = job.job_id;
    saveWorkflow(workflow);

    if (OPEN.has(job.status) && !["needs_speaker", "needs_reference"].includes(job.status)) {
      job = await request(`/api/v1/jobs/${encodeURIComponent(job.job_id)}`);
    }
    if (job.status === "needs_speaker") {
      setStatus("VoiceRig fandt flere speakers. Vælg den rigtige i Stemme-fanen; person-buildet fortsætter automatisk bagefter.");
      return workflow;
    }
    if (job.status === "needs_reference") {
      setStatus("VoiceRig kræver ét reference-review. Vælg den bedste prøve i Stemme-fanen; person-buildet fortsætter automatisk bagefter.");
      return workflow;
    }
    if (FAIL.has(job.status)) throw new Error(job.error || job.message || `VoiceRig-job ${job.status}.`);
    if (job.status === "succeeded") {
      workflow.voice_revision = job.voice_revision;
      saveWorkflow(workflow);
    } else {
      setStatus(`${job.message || job.stage || "VoiceRig bygger …"}${Number.isFinite(Number(job.progress)) ? ` · ${Number(job.progress)}%` : ""}`);
    }
    return workflow;
  }

  async function tick() {
    clearTimeout(timer);
    ensureUi();
    const id = personId();
    const button = $("autoPersonBuildButton");
    if (!id) return schedule(2000);
    let workflow = loadWorkflow(id);
    if (!workflow) {
      if (button) button.disabled = false;
      return schedule(3000);
    }
    if (button) button.disabled = workflow.state !== "failed" && workflow.state !== "complete";

    try {
      const [profile, jobsPayload] = await Promise.all([
        request(`/api/v1/people/${encodeURIComponent(id)}`),
        request(`/api/v1/jobs?person_id=${encodeURIComponent(id)}`),
      ]);
      const jobs = Array.isArray(jobsPayload.jobs) ? jobsPayload.jobs : [];

      if (!workflow.body_revision) {
        let bodyJob = jobs.find((item) => item?.job_id === workflow.body_job_id) || null;
        if (!bodyJob) bodyJob = await request(`/api/v1/jobs/${encodeURIComponent(workflow.body_job_id)}`);
        if (FAIL.has(bodyJob.status)) throw new Error(bodyJob.error || `Body-build ${bodyJob.status}.`);
        if (bodyJob.status !== "succeeded") {
          setStatus(`Krop: ${bodyJob.status}${bodyJob.error ? ` · ${bodyJob.error}` : ""}`);
          return schedule(2000);
        }
        if (!bodyJob.body_revision) throw new Error("Body-build sluttede uden en registreret body revision.");
        workflow.body_revision = bodyJob.body_revision;
        workflow.state = "components";
        saveWorkflow(workflow);
      }

      workflow = await ensurePersonality(workflow, profile);
      const refreshedJobs = (await request(`/api/v1/jobs?person_id=${encodeURIComponent(id)}`)).jobs || [];
      workflow = await ensureVoice(workflow, refreshedJobs);

      if (workflow.personality_revision && workflow.voice_revision) {
        workflow.state = "complete";
        workflow.completed_utc = new Date().toISOString();
        saveWorkflow(workflow);
        setStatus(`Klar til samlet audition: ${workflow.body_revision} + ${workflow.voice_revision} + ${workflow.personality_revision}.`);
        if ($("autoPersonalityStatus")) {
          $("autoPersonalityStatus").textContent = workflow.personality_transcript_count > 0
            ? `${workflow.personality_revision} er source-bundet med transcript/caption speaking-style evidence.`
            : `${workflow.personality_revision} er source-bundet med neutral fallback, fordi der ikke fandtes transcript/caption-evidence.`;
        }
        if (button) button.disabled = false;
        clearWorkflow(id);
        setTimeout(() => window.location.reload(), 800);
        return;
      }
      schedule(2000);
    } catch (error) {
      workflow.state = "failed";
      workflow.error = error.message;
      saveWorkflow(workflow);
      setStatus(error.message, true);
      if (button) button.disabled = false;
      schedule(5000);
    }
  }

  function schedule(delay = 2000) {
    clearTimeout(timer);
    timer = setTimeout(() => void tick(), delay);
  }

  window.addEventListener("DOMContentLoaded", () => {
    ensureUi();
    const idNode = $("personId");
    if (idNode) {
      new MutationObserver(() => schedule(0)).observe(idNode, { childList: true, characterData: true, subtree: true });
    }
    void tick();
  }, { once: true });
})();
