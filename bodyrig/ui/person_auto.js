(() => {
  const $ = (id) => document.getElementById(id);

  async function request(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body !== undefined && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    const response = await fetch(path, { ...options, headers });
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

  async function profile() {
    const id = personId();
    if (!id) throw new Error("Ingen person er valgt.");
    return request(`/api/v1/people/${encodeURIComponent(id)}`);
  }

  function latestBodyRevision(value) {
    const items = value?.body_revisions || [];
    return items.length ? items[items.length - 1].revision_id : null;
  }

  function setStatus(id, text, failed = false) {
    const element = $(id);
    if (!element) return;
    element.textContent = text;
    element.classList.toggle("error", failed);
  }

  function replaceManualCards() {
    const voiceSplit = document.querySelector("#tab-voice .split");
    const oldVoice = voiceSplit?.querySelector("article.card");
    if (voiceSplit && oldVoice && !$("autoVoiceCard")) {
      oldVoice.hidden = true;
      const card = document.createElement("article");
      card.className = "card";
      card.id = "autoVoiceCard";
      card.innerHTML = `
        <div class="card-label">Automatisk stemme fra personens Stash-kilder</div>
        <p id="autoVoiceStatus" class="muted-text">BodyRig bruger den source-bundne body-kandidat som authority og sender de samme verificerede mediefiler til VoiceRig.</p>
        <div class="field-row">
          <div>
            <label for="autoVoiceLanguage">Sprog</label>
            <input id="autoVoiceLanguage" value="en" maxlength="32">
          </div>
          <div>
            <label>Source authority</label>
            <div id="autoVoiceSource" class="proposal">Kontrolleres ved build.</div>
          </div>
        </div>
        <button id="autoVoiceBuildButton" class="primary full">Byg stemmen automatisk</button>
        <div id="autoVoiceChoices" class="revision-list"></div>
        <p class="fine-print">Eksisterende VoiceRig-stemmer kan fortsat eksistere som drafts, men Person Studio bygger som standard en ny stemme fra denne persons egne Stash-kilder.</p>`;
      voiceSplit.insertBefore(card, oldVoice);
      $("autoVoiceBuildButton").addEventListener("click", startVoiceBuild);
    }

    const personalitySplit = document.querySelector("#tab-personality .split");
    const oldPersonality = personalitySplit?.querySelector("article.card");
    if (personalitySplit && oldPersonality && !$("autoPersonalityCard")) {
      oldPersonality.hidden = true;
      const card = document.createElement("article");
      card.className = "card";
      card.id = "autoPersonalityCard";
      card.innerHTML = `
        <div class="card-label">Automatisk personality fra samme person-authority</div>
        <p id="autoPersonalityStatus" class="muted-text">BodyRig opretter en source-bundet, konservativ baseline automatisk fra den validerede body/source authority. Den opfinder ikke biografi eller minder.</p>
        <button id="autoPersonalityBuildButton" class="primary full">Byg personality automatisk</button>
        <p class="fine-print">Dette fjerner den blanke manuelle start. Transcript-/adfærds-evidence kan senere forfine kandidaten; uden sådan evidence forbliver baseline bevidst konservativ.</p>`;
      personalitySplit.insertBefore(card, oldPersonality);
      $("autoPersonalityBuildButton").addEventListener("click", buildPersonality);
    }
  }

  async function startVoiceBuild() {
    const button = $("autoVoiceBuildButton");
    const choices = $("autoVoiceChoices");
    if (button) button.disabled = true;
    if (choices) choices.innerHTML = "";
    try {
      const value = await profile();
      const bodyRevision = latestBodyRevision(value);
      if (!bodyRevision) throw new Error("Der er ingen body-kandidat endnu. Body-build skal gennemføre først.");
      if (!value.source) throw new Error("Personen har ingen Stash source-binding.");
      $("autoVoiceSource").textContent = `${value.source.performer_name} · ${bodyRevision}`;
      const language = ($("autoVoiceLanguage")?.value || "en").trim() || "en";
      setStatus("autoVoiceStatus", "Starter source-derived VoiceRig-build …");
      const job = await request(
        `/api/v1/people/${encodeURIComponent(value.person_id)}/voice/build-from-source?body_revision=${encodeURIComponent(bodyRevision)}&language=${encodeURIComponent(language)}`,
        { method: "POST" },
      );
      await pollVoiceJob(job.job_id);
    } catch (error) {
      setStatus("autoVoiceStatus", error.message, true);
      if (button) button.disabled = false;
    }
  }

  async function pollVoiceJob(jobId) {
    const button = $("autoVoiceBuildButton");
    const choices = $("autoVoiceChoices");
    for (;;) {
      const job = await request(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
      const progress = Number.isFinite(job.progress) ? ` · ${job.progress}%` : "";
      setStatus("autoVoiceStatus", `${job.message || job.stage || job.status}${progress}`, job.status === "failed");

      if (job.status === "needs_speaker") {
        renderSpeakerChoices(job);
        if (button) button.disabled = false;
        return;
      }
      if (job.status === "needs_reference") {
        renderReferenceChoices(job);
        if (button) button.disabled = false;
        return;
      }
      if (job.status === "succeeded") {
        if (choices) choices.innerHTML = "";
        setStatus("autoVoiceStatus", `Færdig: ${job.voice_revision} · ${job.voice_package}`);
        setTimeout(() => window.location.reload(), 500);
        return;
      }
      if (["failed", "canceled"].includes(job.status)) {
        if (choices) choices.innerHTML = "";
        setStatus("autoVoiceStatus", job.error || job.message || `Voice-build ${job.status}.`, true);
        if (button) button.disabled = false;
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }

  function renderSpeakerChoices(job) {
    const target = $("autoVoiceChoices");
    if (!target) return;
    const values = Array.isArray(job.speaker_choices) ? job.speaker_choices : [];
    target.innerHTML = '<div class="muted-text">VoiceRig kunne ikke vælge speaker entydigt. Vælg kun hvis den automatiske disambiguering beder om det:</div>';
    for (const item of values) {
      const anchor = String(item?.anchor || item?.speaker_anchor || item?.id || "").trim();
      if (!anchor) continue;
      const button = document.createElement("button");
      button.className = "secondary full";
      button.textContent = String(item?.label || item?.name || anchor);
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await request(`/api/v1/jobs/${encodeURIComponent(job.job_id)}/speaker?anchor=${encodeURIComponent(anchor)}`, { method: "POST" });
          target.innerHTML = "";
          await pollVoiceJob(job.job_id);
        } catch (error) {
          setStatus("autoVoiceStatus", error.message, true);
          button.disabled = false;
        }
      });
      target.appendChild(button);
    }
  }

  function renderReferenceChoices(job) {
    const target = $("autoVoiceChoices");
    if (!target) return;
    const values = Array.isArray(job.reference_choices) ? job.reference_choices : [];
    target.innerHTML = '<div class="muted-text">VoiceRig kræver referencevalg. Dette vises kun når automatisk referencevalg ikke er sikkert:</div>';
    values.slice(0, 4).forEach((item, index) => {
      const choice = Number(item?.choice || item?.index || index + 1);
      const button = document.createElement("button");
      button.className = "secondary full";
      button.textContent = String(item?.label || item?.name || `Reference ${choice}`);
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await request(`/api/v1/jobs/${encodeURIComponent(job.job_id)}/reference?choice=${encodeURIComponent(choice)}`, { method: "POST" });
          target.innerHTML = "";
          await pollVoiceJob(job.job_id);
        } catch (error) {
          setStatus("autoVoiceStatus", error.message, true);
          button.disabled = false;
        }
      });
      target.appendChild(button);
    });
  }

  async function buildPersonality() {
    const button = $("autoPersonalityBuildButton");
    if (button) button.disabled = true;
    try {
      const value = await profile();
      const bodyRevision = latestBodyRevision(value);
      if (!bodyRevision) throw new Error("Der er ingen source-bundet body-kandidat endnu.");
      if (!value.source) throw new Error("Personen har ingen Stash source-binding.");
      setStatus("autoPersonalityStatus", "Bygger source-bundet personality-baseline …");
      const payload = {
        default_language: "en",
        communication: {
          directness: 0.5,
          warmth: 0.5,
          playfulness: 0.5,
          formality: 0.5,
          verbosity: 0.5,
          initiative: 0.5,
        },
        authored_notes: "Source-conservative automatic baseline. Do not invent biography, memories, relationships, private facts, or behavioral traits that are not supported by source evidence.",
        style_exemplars: [],
        style_report: null,
        style_approval: null,
        body_revision: bodyRevision,
        feedback: `Automatic source-grounded baseline from ${bodyRevision}`,
      };
      const result = await request(
        `/api/v1/people/${encodeURIComponent(value.person_id)}/personality/guided/revisions`,
        { method: "POST", body: JSON.stringify(payload) },
      );
      setStatus("autoPersonalityStatus", `Færdig: ${result.saved_personality_revision}. Baseline er source-bundet og klar til samlet audition.`);
      setTimeout(() => window.location.reload(), 500);
    } catch (error) {
      setStatus("autoPersonalityStatus", error.message, true);
      if (button) button.disabled = false;
    }
  }

  window.addEventListener("DOMContentLoaded", replaceManualCards, { once: true });
})();
