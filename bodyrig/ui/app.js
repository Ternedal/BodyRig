const state = { people: [], selected: null, selectedStash: null, tab: "overview", jobTimer: null };

const $ = (id) => document.getElementById(id);

function toast(message, error = false) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("error", error);
  el.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.add("hidden"), 4200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const type = response.headers.get("content-type") || "";
  const payload = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "object" ? (payload.detail || JSON.stringify(payload)) : payload;
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return payload;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[ch]));
}

function short(value, n = 48) {
  if (!value) return "—";
  return value.length > n ? `${value.slice(0, n - 1)}…` : value;
}

function revisionById(profile, kind, id) {
  if (!id) return null;
  return (profile[`${kind}_revisions`] || []).find((item) => item.revision_id === id) || null;
}

function activeBundle(profile) {
  const id = profile?.active_person_revision;
  if (!id) return null;
  return (profile.person_revisions || []).find((item) => item.revision_id === id) || null;
}

function activeComponentId(profile, kind) {
  const bundle = activeBundle(profile);
  return bundle ? bundle[`${kind}_revision`] : null;
}

function latestRevision(profile, kind) {
  const items = profile?.[`${kind}_revisions`] || [];
  return items.length ? items[items.length - 1] : null;
}

function renderPeople() {
  const list = $("personList");
  list.innerHTML = "";
  for (const person of state.people) {
    const button = document.createElement("button");
    button.className = `person-item${state.selected?.person_id === person.person_id ? " active" : ""}`;
    const active = person.active_person_revision ? ` · ${person.active_person_revision}` : " · ikke samlet";
    button.innerHTML = `<strong>${escapeHtml(person.display_name)}</strong><span>${escapeHtml(person.source?.performer_name || "Lokal profil")}${escapeHtml(active)}</span>`;
    button.addEventListener("click", () => selectPerson(person.person_id));
    list.appendChild(button);
  }
}

function renderRevisionList(targetId, profile, kind, labelField) {
  const target = $(targetId);
  const items = profile[`${kind}_revisions`] || [];
  const activeId = activeComponentId(profile, kind);
  target.innerHTML = "";
  if (!items.length) {
    target.innerHTML = `<div class="muted-text">Ingen ${kind}-kandidater endnu.</div>`;
    return;
  }
  [...items].reverse().forEach((item) => {
    const row = document.createElement("div");
    const isActive = item.revision_id === activeId;
    row.className = `revision-item${isActive ? " active" : ""}`;
    const feedback = item.feedback ? `<div class="revision-feedback">${escapeHtml(item.feedback)}</div>` : "";
    row.innerHTML = `
      <div class="revision-top">
        <div><div class="revision-id">${escapeHtml(item.revision_id)}</div><div class="revision-meta">${escapeHtml(item[labelField] || "")}</div></div>
        ${isActive ? '<span class="badge">I aktiv person</span>' : `<button class="secondary use-candidate" data-kind="${kind}" data-revision="${item.revision_id}">Brug i samling</button>`}
      </div>${feedback}`;
    target.appendChild(row);
  });
  target.querySelectorAll(".use-candidate").forEach((button) => {
    button.addEventListener("click", () => useCandidate(button.dataset.kind, button.dataset.revision));
  });
}

function renderPersonRevisions(profile) {
  const target = $("personRevisions");
  const items = profile.person_revisions || [];
  target.innerHTML = "";
  if (!items.length) {
    target.innerHTML = '<div class="muted-text">Ingen godkendte Person Revisions endnu.</div>';
    return;
  }
  [...items].reverse().forEach((item) => {
    const active = item.revision_id === profile.active_person_revision;
    const row = document.createElement("div");
    row.className = `revision-item${active ? " active" : ""}`;
    row.innerHTML = `
      <div class="revision-top">
        <div>
          <div class="revision-id">${escapeHtml(item.revision_id)}</div>
          <div class="revision-meta">${escapeHtml(item.body_revision)} · ${escapeHtml(item.voice_revision)} · ${escapeHtml(item.personality_revision)}</div>
        </div>
        ${active ? '<span class="badge">Aktiv person</span>' : `<button class="secondary activate-person" data-revision="${item.revision_id}">Aktivér samlet</button>`}
      </div>
      <div class="revision-feedback">${escapeHtml(item.compatibility_review.note)}</div>`;
    target.appendChild(row);
  });
  target.querySelectorAll(".activate-person").forEach((button) => {
    button.addEventListener("click", () => activatePersonRevision(button.dataset.revision));
  });
}

function renderHistory(profile) {
  const target = $("historyList");
  const all = [];
  for (const kind of ["body", "voice", "personality"]) {
    for (const item of profile[`${kind}_revisions`] || []) all.push({ ...item, kind });
  }
  for (const item of profile.person_revisions || []) all.push({ ...item, kind: "person" });
  all.sort((a, b) => String(b.created_utc).localeCompare(String(a.created_utc)));
  target.innerHTML = "";
  if (!all.length) {
    target.innerHTML = '<div class="muted-text">Ingen revisioner endnu.</div>';
    return;
  }
  for (const item of all) {
    const row = document.createElement("div");
    row.className = "revision-item";
    let title = "";
    if (item.kind === "body") title = item.body_id;
    else if (item.kind === "voice") title = item.voice_id;
    else if (item.kind === "personality") title = short(item.instructions, 80);
    else title = `${item.body_revision} + ${item.voice_revision} + ${item.personality_revision}`;
    const note = item.kind === "person" ? item.compatibility_review.note : item.feedback;
    row.innerHTML = `<div class="revision-top"><div><div class="revision-id">${escapeHtml(item.revision_id)}</div><div class="revision-meta">${escapeHtml(title)}</div></div><span class="badge muted">${escapeHtml(item.kind)}</span></div>${note ? `<div class="revision-feedback">${escapeHtml(note)}</div>` : ""}`;
    target.appendChild(row);
  }
}

function fillSelect(id, items, selected, labelField) {
  const select = $(id);
  const previous = select.value;
  select.innerHTML = '<option value="">Vælg revision</option>';
  for (const item of items) {
    const option = document.createElement("option");
    option.value = item.revision_id;
    option.textContent = `${item.revision_id} · ${short(item[labelField] || "", 56)}`;
    select.appendChild(option);
  }
  const wanted = [previous, selected, items.at(-1)?.revision_id].find((value) => value && items.some((item) => item.revision_id === value));
  select.value = wanted || "";
}

function renderSelected() {
  const p = state.selected;
  $("emptyState").classList.toggle("hidden", Boolean(p));
  $("personView").classList.toggle("hidden", !p);
  renderPeople();
  if (!p) return;

  const bundle = activeBundle(p);
  const activeBodyId = bundle?.body_revision || null;
  const activeVoiceId = bundle?.voice_revision || null;
  const activePersonalityId = bundle?.personality_revision || null;

  $("personId").textContent = p.person_id;
  $("personName").textContent = p.display_name;
  $("personSource").textContent = p.source ? `Stash: ${p.source.performer_name} · id ${p.source.performer_id}` : "Ingen Stash-binding";
  $("personActive").textContent = `Person ${p.active_person_revision || "—"}`;
  $("bodyActive").textContent = `Krop ${activeBodyId || "—"}`;
  $("voiceActive").textContent = `Stemme ${activeVoiceId || "—"}`;
  $("personalityActive").textContent = `Personlighed ${activePersonalityId || "—"}`;
  $("overviewPersonRevision").textContent = p.active_person_revision || "Ingen";
  $("overviewBody").textContent = activeBodyId || "Ingen";
  $("overviewVoice").textContent = activeVoiceId || "Ingen";
  $("overviewPersonality").textContent = activePersonalityId || "Ingen";
  $("overviewCompatibility").textContent = bundle ? "Godkendt samlet" : "Ikke samlet";
  $("overviewCompatibilityNote").textContent = bundle ? bundle.compatibility_review.note : "Krop, stemme og personlighed skal godkendes som én samlet person før aktivering.";

  $("buildSourceText").textContent = p.source ? `Klar til build fra ${p.source.performer_name} (Stash id ${p.source.performer_id}).` : "Bind personen til en Stash performer først.";
  $("buildBodyButton").disabled = !p.source;
  $("bodyCount").textContent = String(p.body_revisions.length);
  renderRevisionList("bodyRevisions", p, "body", "body_id");
  renderRevisionList("voiceRevisions", p, "voice", "voice_id");
  renderRevisionList("personalityRevisions", p, "personality", "default_language");
  renderPersonRevisions(p);
  renderHistory(p);

  const previewBody = latestRevision(p, "body") || revisionById(p, "body", activeBodyId);
  $("bodyRevisionLabel").textContent = previewBody?.revision_id || "Ingen revision";
  $("previewEmpty").classList.toggle("hidden", Boolean(previewBody));
  $("bodyPreview").classList.toggle("hidden", !previewBody);
  if (previewBody) {
    $("bodyPreview").src = `/api/v1/people/${encodeURIComponent(p.person_id)}/body/preview?revision=${encodeURIComponent(previewBody.revision_id)}&v=${encodeURIComponent(previewBody.package_sha256)}`;
  } else {
    $("bodyPreview").removeAttribute("src");
  }

  const personality = latestRevision(p, "personality") || revisionById(p, "personality", activePersonalityId);
  if (personality) {
    $("personalityInstructions").value = personality.instructions;
    $("personalityLanguage").value = personality.default_language;
    $("personalityStyle").value = personality.style_notes || "";
  } else {
    $("personalityInstructions").value = "";
    $("personalityLanguage").value = "da";
    $("personalityStyle").value = "";
  }

  fillSelect("assembleBody", p.body_revisions, activeBodyId, "body_id");
  fillSelect("assembleVoice", p.voice_revisions, activeVoiceId, "voice_id");
  fillSelect("assemblePersonality", p.personality_revisions, activePersonalityId, "default_language");
  $("approvePersonButton").disabled = !(p.body_revisions.length && p.voice_revisions.length && p.personality_revisions.length);
}

async function loadPeople(preferId = null) {
  const payload = await api("/api/v1/people");
  state.people = payload.people || [];
  const wanted = preferId || state.selected?.person_id;
  if (wanted && state.people.some((item) => item.person_id === wanted)) {
    state.selected = await api(`/api/v1/people/${encodeURIComponent(wanted)}`);
  } else if (state.people.length && !state.selected) {
    state.selected = await api(`/api/v1/people/${encodeURIComponent(state.people[0].person_id)}`);
  } else if (!state.people.length) {
    state.selected = null;
  }
  renderSelected();
}

async function selectPerson(personId) {
  try {
    state.selected = await api(`/api/v1/people/${encodeURIComponent(personId)}`);
    renderSelected();
  } catch (error) { toast(error.message, true); }
}

async function health() {
  try {
    const payload = await api("/api/v1/health");
    $("healthBadge").textContent = payload.ok ? "Lokal" : "Fejl";
    $("healthBadge").classList.toggle("muted", !payload.ok);
  } catch {
    $("healthBadge").textContent = "Offline";
  }
}

function openNewPerson() {
  state.selectedStash = null;
  $("newPersonName").value = "";
  $("stashSearchInput").value = "";
  $("stashResults").innerHTML = "";
  $("stashStatus").textContent = "";
  $("selectedStash").classList.add("hidden");
  $("newPersonDialog").showModal();
}

async function searchStash() {
  const q = $("stashSearchInput").value.trim();
  if (!q) return;
  $("stashStatus").textContent = "Søger …";
  $("stashResults").innerHTML = "";
  try {
    const payload = await api(`/api/v1/stash/search?q=${encodeURIComponent(q)}&limit=15`);
    $("stashStatus").textContent = `${payload.performers.length} fundet · Stash ${payload.version}`;
    for (const performer of payload.performers) {
      const row = document.createElement("div");
      row.className = "stash-result";
      row.innerHTML = `<div><strong>${escapeHtml(performer.name)}</strong><div class="muted-text">id ${escapeHtml(performer.id)}${performer.disambiguation ? ` · ${escapeHtml(performer.disambiguation)}` : ""}</div></div><button type="button" class="secondary">Vælg</button>`;
      row.querySelector("button").addEventListener("click", () => {
        state.selectedStash = performer;
        $("selectedStash").textContent = `Valgt: ${performer.name} · Stash id ${performer.id}`;
        $("selectedStash").classList.remove("hidden");
        if (!$("newPersonName").value.trim()) $("newPersonName").value = performer.name;
      });
      $("stashResults").appendChild(row);
    }
  } catch (error) {
    $("stashStatus").textContent = `Stash-fejl: ${error.message}`;
  }
}

async function createPerson() {
  const displayName = $("newPersonName").value.trim();
  if (!displayName) { toast("Skriv et navn først.", true); return; }
  try {
    const created = await api("/api/v1/people", {
      method: "POST",
      body: JSON.stringify({ display_name: displayName, aliases: [], stash_performer: state.selectedStash }),
    });
    $("newPersonDialog").close();
    await loadPeople(created.person_id);
    toast(`${created.display_name} er oprettet.`);
  } catch (error) { toast(error.message, true); }
}

async function savePersonality() {
  if (!state.selected) return;
  const instructions = $("personalityInstructions").value.trim();
  if (!instructions) { toast("Personligheden mangler instructions.", true); return; }
  try {
    state.selected = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/personality/revisions`, {
      method: "POST",
      body: JSON.stringify({
        instructions,
        default_language: $("personalityLanguage").value.trim() || "da",
        style_notes: $("personalityStyle").value.trim(),
        feedback: $("personalityFeedback").value.trim(),
      }),
    });
    $("personalityFeedback").value = "";
    renderSelected();
    toast("Ny personality-kandidat gemt. Den aktive person er uændret.");
  } catch (error) { toast(error.message, true); }
}

async function attachVoice() {
  if (!state.selected) return;
  const voiceId = $("voiceIdInput").value.trim();
  if (!voiceId) { toast("Voice ID mangler.", true); return; }
  try {
    state.selected = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/voice/revisions`, {
      method: "POST",
      body: JSON.stringify({
        voice_id: voiceId,
        package_path: $("voicePathInput").value.trim() || null,
        feedback: $("voiceFeedbackInput").value.trim(),
      }),
    });
    $("voiceFeedbackInput").value = "";
    renderSelected();
    toast("Ny voice-kandidat gemt. Den aktive person er uændret.");
  } catch (error) { toast(error.message, true); }
}

function useCandidate(kind, revisionId) {
  const select = $(`assemble${kind[0].toUpperCase()}${kind.slice(1)}`);
  if (select) select.value = revisionId;
  switchTab("assemble");
}

async function approvePersonRevision() {
  if (!state.selected) return;
  const bodyRevision = $("assembleBody").value;
  const voiceRevision = $("assembleVoice").value;
  const personalityRevision = $("assemblePersonality").value;
  const note = $("compatibilityNote").value.trim();
  if (!bodyRevision || !voiceRevision || !personalityRevision) { toast("Vælg krop, stemme og personlighed.", true); return; }
  if (!note) { toast("Skriv en compatibility-note.", true); return; }
  try {
    state.selected = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/revisions`, {
      method: "POST",
      body: JSON.stringify({
        body_revision: bodyRevision,
        voice_revision: voiceRevision,
        personality_revision: personalityRevision,
        body_voice_match: $("matchBodyVoice").checked,
        voice_personality_match: $("matchVoicePersonality").checked,
        body_personality_match: $("matchBodyPersonality").checked,
        overall_coherent: $("matchOverall").checked,
        compatibility_note: note,
        feedback: $("personRevisionFeedback").value.trim(),
        activate: true,
      }),
    });
    for (const id of ["matchBodyVoice", "matchVoicePersonality", "matchBodyPersonality", "matchOverall"]) $(id).checked = false;
    $("compatibilityNote").value = "";
    $("personRevisionFeedback").value = "";
    renderSelected();
    toast(`${state.selected.active_person_revision} er nu aktiv som samlet person.`);
  } catch (error) { toast(error.message, true); }
}

async function activatePersonRevision(revisionId) {
  if (!state.selected) return;
  try {
    state.selected = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/revisions/${encodeURIComponent(revisionId)}/activate`, { method: "POST" });
    renderSelected();
    toast(`${revisionId} er nu aktiv som samlet person.`);
  } catch (error) { toast(error.message, true); }
}

async function proposeBodyChanges() {
  if (!state.selected) return;
  const feedback = $("bodyFeedback").value.trim();
  if (!feedback) { toast("Skriv først hvad du vil ændre.", true); return; }
  try {
    const proposal = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/body/propose`, {
      method: "POST",
      body: JSON.stringify({ feedback }),
    });
    if (!proposal.changes.length) {
      $("bodyProposal").textContent = "Ingen sikker struktureret ændring fundet. BodyRig ændrer ikke noget på et gæt.";
      return;
    }
    $("bodyProposal").innerHTML = `<strong>Forslag — ikke anvendt endnu</strong>\n${proposal.changes.map((c) => `${c.field}: ${c.delta > 0 ? "+" : ""}${c.delta}`).join("\n")}`;
  } catch (error) { toast(error.message, true); }
}

async function pollJob(jobId) {
  clearTimeout(state.jobTimer);
  try {
    const job = await api(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
    if (job.status === "succeeded") {
      await loadPeople(state.selected?.person_id || job.person_id);
      toast(`${job.body_revision} er bygget som ny body-kandidat. Den aktive person er uændret.`);
      return;
    }
    if (["failed", "canceled", "interrupted"].includes(job.status)) {
      toast(job.error || `Body-build ${job.status}`, true);
      return;
    }
    state.jobTimer = setTimeout(() => pollJob(jobId), 2000);
  } catch (error) { toast(error.message, true); }
}

async function buildBody() {
  if (!state.selected?.source) return;
  try {
    const result = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/body/build`, { method: "POST", body: JSON.stringify({}) });
    toast(`Body-build startet: ${result.job_id}`);
    pollJob(result.job_id);
  } catch (error) { toast(error.message, true); }
}

function switchTab(name) {
  state.tab = name;
  document.querySelectorAll(".tab").forEach((el) => el.classList.toggle("active", el.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((el) => el.classList.add("hidden"));
  $(`tab-${name}`).classList.remove("hidden");
}

function wire() {
  $("newPersonButton").addEventListener("click", openNewPerson);
  $("emptyCreateButton").addEventListener("click", openNewPerson);
  $("stashSearchButton").addEventListener("click", searchStash);
  $("stashSearchInput").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); searchStash(); } });
  $("createPersonButton").addEventListener("click", createPerson);
  $("savePersonalityButton").addEventListener("click", savePersonality);
  $("attachVoiceButton").addEventListener("click", attachVoice);
  $("approvePersonButton").addEventListener("click", approvePersonRevision);
  $("proposeBodyChanges").addEventListener("click", proposeBodyChanges);
  $("buildBodyButton").addEventListener("click", buildBody);
  document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => switchTab(button.dataset.tab)));
}

(async function start() {
  wire();
  await health();
  try { await loadPeople(); } catch (error) { toast(error.message, true); }
})();
