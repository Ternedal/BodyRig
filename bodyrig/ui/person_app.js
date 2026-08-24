const state = {
  people: [],
  selected: null,
  selectedStash: null,
  voiceLibrary: [],
  modelLibrary: [],
  tab: "overview",
  jobTimer: null,
  assembly: null,
};

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
  const headers = { ...(options.headers || {}) };
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

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[ch]));
}

function short(value, n = 56) {
  const text = String(value || "");
  if (!text) return "—";
  return text.length > n ? `${text.slice(0, n - 1)}…` : text;
}

function revisionById(profile, kind, id) {
  if (!id) return null;
  return (profile?.[`${kind}_revisions`] || []).find((item) => item.revision_id === id) || null;
}

function activeBundle(profile) {
  const id = profile?.active_person_revision;
  return id ? (profile.person_revisions || []).find((item) => item.revision_id === id) || null : null;
}

function activeComponentId(profile, kind) {
  const bundle = activeBundle(profile);
  return bundle ? bundle[`${kind}_revision`] : null;
}

function latestRevision(profile, kind) {
  const items = profile?.[`${kind}_revisions`] || [];
  return items.length ? items[items.length - 1] : null;
}

function selectedAssemblyKey() {
  return [
    $("assembleBody")?.value || "",
    $("assembleVoice")?.value || "",
    $("assemblePersonality")?.value || "",
  ].join("|");
}

function selectedAuditionKey() {
  return [
    selectedAssemblyKey(),
    $("assemblyModel")?.value || "",
    $("assemblyPrompt")?.value.trim() || "",
  ].join("|");
}

function setReviewEnabled(enabled) {
  for (const id of ["matchBodyVoice", "matchVoicePersonality", "matchBodyPersonality", "matchOverall", "compatibilityNote", "personRevisionFeedback"]) {
    $(id).disabled = !enabled;
  }
  if (!enabled) {
    for (const id of ["matchBodyVoice", "matchVoicePersonality", "matchBodyPersonality", "matchOverall"]) $(id).checked = false;
    $("assemblyReadyBadge").textContent = "Låst";
    $("assemblyReadyBadge").classList.add("muted");
    $("assemblyReviewStatus").textContent = "ModelRig-audition skal være komplet før review åbnes.";
  } else {
    $("assemblyReadyBadge").textContent = "Klar til review";
    $("assemblyReadyBadge").classList.remove("muted");
    $("assemblyReviewStatus").textContent = "Du har set kroppen, set personality-kilden og hørt det faktiske ModelRig-svar med den valgte VoiceRig-stemme.";
  }
  updateApprovalButton();
}

function resetAssembly(message = "Ingen audition kørt.") {
  state.assembly = null;
  $("assemblyFingerprint").textContent = message;
  $("assemblyBodyState").textContent = "Ikke loadet";
  $("assemblyBodyState").classList.add("muted");
  $("assemblyBodyEmpty").classList.remove("hidden");
  $("assemblyBodyPreview").classList.add("hidden");
  $("assemblyBodyPreview").removeAttribute("src");
  $("assemblyVoiceState").textContent = "Ikke hørt";
  $("assemblyVoiceState").classList.add("muted");
  $("assemblyVoiceAudio").removeAttribute("src");
  $("assemblyVoiceAudio").load();
  $("assemblyReply").textContent = "Kør audition først.";
  $("assemblyPersonalityState").textContent = "Ikke vist";
  $("assemblyPersonalityState").classList.add("muted");
  $("assemblyPersonalityMeta").textContent = "";
  $("assemblyPersonalityText").textContent = "Kør audition først.";
  setReviewEnabled(false);
}

function auditionReady() {
  const a = state.assembly;
  return Boolean(
    a &&
    a.key === selectedAuditionKey() &&
    a.bodyLoaded &&
    a.voiceHeard &&
    a.personalityShown &&
    a.replyShown &&
    a.auditionId
  );
}

function updateAssemblyReadiness() {
  setReviewEnabled(auditionReady());
}

function updateApprovalButton() {
  const allChecked = ["matchBodyVoice", "matchVoicePersonality", "matchBodyPersonality", "matchOverall"].every((id) => $(id).checked);
  const note = $("compatibilityNote").value.trim();
  $("approvePersonButton").disabled = !(auditionReady() && allChecked && note);
}

function renderPeople() {
  const list = $("personList");
  list.innerHTML = "";
  for (const person of state.people) {
    const button = document.createElement("button");
    button.className = `person-item${state.selected?.person_id === person.person_id ? " active" : ""}`;
    const suffix = person.active_person_revision ? ` · ${person.active_person_revision}` : " · ikke samlet";
    button.innerHTML = `<strong>${escapeHtml(person.display_name)}</strong><span>${escapeHtml(person.source?.performer_name || "Lokal profil")}${escapeHtml(suffix)}</span>`;
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
    const active = item.revision_id === activeId;
    const label = item[labelField] || item.voice_package || "";
    const row = document.createElement("div");
    row.className = `revision-item${active ? " active" : ""}`;
    row.innerHTML = `
      <div class="revision-top">
        <div><div class="revision-id">${escapeHtml(item.revision_id)}</div><div class="revision-meta">${escapeHtml(label)}</div></div>
        ${active ? '<span class="badge">I aktiv person</span>' : `<button class="secondary use-candidate" data-kind="${kind}" data-revision="${item.revision_id}">Brug i samling</button>`}
      </div>
      ${item.feedback ? `<div class="revision-feedback">${escapeHtml(item.feedback)}</div>` : ""}`;
    target.appendChild(row);
  });
  target.querySelectorAll(".use-candidate").forEach((button) => button.addEventListener("click", () => useCandidate(button.dataset.kind, button.dataset.revision)));
}

function renderPersonRevisions(profile) {
  const target = $("personRevisions");
  target.innerHTML = "";
  const items = profile.person_revisions || [];
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
        <div><div class="revision-id">${escapeHtml(item.revision_id)}</div><div class="revision-meta">${escapeHtml(item.body_revision)} · ${escapeHtml(item.voice_revision)} · ${escapeHtml(item.personality_revision)}</div></div>
        ${active ? '<span class="badge">Aktiv person</span>' : `<button class="secondary activate-person" data-revision="${item.revision_id}">Aktivér samlet</button>`}
      </div><div class="revision-feedback">${escapeHtml(item.compatibility_review.note)}</div>`;
    target.appendChild(row);
  });
  target.querySelectorAll(".activate-person").forEach((button) => button.addEventListener("click", () => activatePersonRevision(button.dataset.revision)));
}

function renderHistory(profile) {
  const target = $("historyList");
  const all = [];
  for (const kind of ["body", "voice", "personality"]) for (const item of profile[`${kind}_revisions`] || []) all.push({ ...item, kind });
  for (const item of profile.person_revisions || []) all.push({ ...item, kind: "person" });
  all.sort((a, b) => String(b.created_utc).localeCompare(String(a.created_utc)));
  target.innerHTML = "";
  if (!all.length) {
    target.innerHTML = '<div class="muted-text">Ingen revisioner endnu.</div>';
    return;
  }
  for (const item of all) {
    let title = "";
    if (item.kind === "body") title = item.body_id;
    else if (item.kind === "voice") title = `${item.voice_id} · ${item.voice_package}`;
    else if (item.kind === "personality") title = short(item.instructions, 80);
    else title = `${item.body_revision} + ${item.voice_revision} + ${item.personality_revision}`;
    const note = item.kind === "person" ? item.compatibility_review.note : item.feedback;
    const row = document.createElement("div");
    row.className = "revision-item";
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
    option.textContent = `${item.revision_id} · ${short(item[labelField] || item.voice_package || "", 56)}`;
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
  const activeBody = bundle?.body_revision || null;
  const activeVoice = bundle?.voice_revision || null;
  const activePersonality = bundle?.personality_revision || null;
  $("personId").textContent = p.person_id;
  $("personName").textContent = p.display_name;
  $("personSource").textContent = p.source ? `Stash: ${p.source.performer_name} · id ${p.source.performer_id}` : "Ingen Stash-binding";
  $("personActive").textContent = `Person ${p.active_person_revision || "—"}`;
  $("bodyActive").textContent = `Krop ${activeBody || "—"}`;
  $("voiceActive").textContent = `Stemme ${activeVoice || "—"}`;
  $("personalityActive").textContent = `Personlighed ${activePersonality || "—"}`;
  $("overviewPersonRevision").textContent = p.active_person_revision || "Ingen";
  $("overviewBody").textContent = activeBody || "Ingen";
  $("overviewVoice").textContent = activeVoice || "Ingen";
  $("overviewPersonality").textContent = activePersonality || "Ingen";
  $("overviewCompatibility").textContent = bundle ? "Godkendt samlet" : "Ikke samlet";
  $("overviewCompatibilityNote").textContent = bundle ? bundle.compatibility_review.note : "Krop, stemme og personlighed skal auditioneres og godkendes som én samlet person før aktivering.";

  $("buildSourceText").textContent = p.source ? `Klar til build fra ${p.source.performer_name} (Stash id ${p.source.performer_id}).` : "Bind personen til en Stash performer først.";
  $("buildBodyButton").disabled = !p.source;
  $("bodyCount").textContent = String(p.body_revisions.length);
  renderRevisionList("bodyRevisions", p, "body", "body_id");
  renderRevisionList("voiceRevisions", p, "voice", "voice_package");
  renderRevisionList("personalityRevisions", p, "personality", "default_language");
  renderPersonRevisions(p);
  renderHistory(p);

  const body = latestRevision(p, "body") || revisionById(p, "body", activeBody);
  $("bodyRevisionLabel").textContent = body?.revision_id || "Ingen revision";
  $("previewEmpty").classList.toggle("hidden", Boolean(body));
  $("bodyPreview").classList.toggle("hidden", !body);
  if (body) $("bodyPreview").src = `/api/v1/people/${encodeURIComponent(p.person_id)}/body/preview?revision=${encodeURIComponent(body.revision_id)}&v=${encodeURIComponent(body.package_sha256)}`;
  else $("bodyPreview").removeAttribute("src");

  const personality = latestRevision(p, "personality") || revisionById(p, "personality", activePersonality);
  $("personalityInstructions").value = personality?.instructions || "";
  $("personalityLanguage").value = personality?.default_language || "da";
  $("personalityStyle").value = personality?.style_notes || "";

  fillSelect("assembleBody", p.body_revisions, activeBody, "body_id");
  fillSelect("assembleVoice", p.voice_revisions, activeVoice, "voice_package");
  fillSelect("assemblePersonality", p.personality_revisions, activePersonality, "default_language");
  resetAssembly("Vælg kandidater, ModelRig-model og prompt og kør en ny audition.");
}

async function loadPeople(preferId = null) {
  const payload = await api("/api/v1/people");
  state.people = payload.people || [];
  const wanted = preferId || state.selected?.person_id;
  if (wanted && state.people.some((item) => item.person_id === wanted)) state.selected = await api(`/api/v1/people/${encodeURIComponent(wanted)}`);
  else if (state.people.length) state.selected = await api(`/api/v1/people/${encodeURIComponent(state.people[0].person_id)}`);
  else state.selected = null;
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

async function loadVoiceLibrary() {
  const select = $("voiceLibrarySelect");
  select.innerHTML = '<option value="">Vælg VoiceRig-stemme</option>';
  $("voiceLibraryStatus").textContent = "Forbinder til VoiceRig…";
  try {
    await api("/api/v1/voicerig/health");
    const payload = await api("/api/v1/voicerig/voices");
    state.voiceLibrary = payload.voices || [];
    for (const voice of state.voiceLibrary) {
      const option = document.createElement("option");
      option.value = voice.package;
      option.textContent = `${voice.name} · ${voice.language || "?"}${voice.is_default ? " · default" : ""}`;
      select.appendChild(option);
    }
    $("voiceLibraryStatus").textContent = `${state.voiceLibrary.length} validerede VoiceRig-stemmer.`;
  } catch (error) {
    state.voiceLibrary = [];
    $("voiceLibraryStatus").textContent = `VoiceRig er ikke klar: ${error.message}`;
  }
}

async function loadModelLibrary() {
  const select = $("assemblyModel");
  const previous = select.value;
  select.innerHTML = '<option value="">Vælg ModelRig-model</option>';
  $("assemblyModelStatus").textContent = "Forbinder til ModelRig…";
  try {
    await api("/api/v1/modelrig/health");
    const payload = await api("/api/v1/modelrig/models");
    state.modelLibrary = payload.models || [];
    for (const model of state.modelLibrary) {
      const option = document.createElement("option");
      option.value = model.name;
      option.textContent = model.name;
      select.appendChild(option);
    }
    if (previous && state.modelLibrary.some((item) => item.name === previous)) select.value = previous;
    else if (state.modelLibrary.length) select.value = state.modelLibrary[0].name;
    $("assemblyModelStatus").textContent = `${state.modelLibrary.length} ModelRig-modeller klar. MODELRIG_TOKEN bruges kun som transport.`;
  } catch (error) {
    state.modelLibrary = [];
    $("assemblyModelStatus").textContent = `ModelRig er ikke klar: ${error.message}`;
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
  } catch (error) { $("stashStatus").textContent = `Stash-fejl: ${error.message}`; }
}

async function createPerson() {
  const displayName = $("newPersonName").value.trim();
  if (!displayName) return toast("Skriv et navn først.", true);
  try {
    const created = await api("/api/v1/people", { method: "POST", body: JSON.stringify({ display_name: displayName, aliases: [], stash_performer: state.selectedStash }) });
    $("newPersonDialog").close();
    await loadPeople(created.person_id);
    toast(`${created.display_name} er oprettet.`);
  } catch (error) { toast(error.message, true); }
}

async function savePersonality() {
  if (!state.selected) return;
  const instructions = $("personalityInstructions").value.trim();
  if (!instructions) return toast("Personligheden mangler instructions.", true);
  try {
    state.selected = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/personality/revisions`, {
      method: "POST",
      body: JSON.stringify({ instructions, default_language: $("personalityLanguage").value.trim() || "da", style_notes: $("personalityStyle").value.trim(), feedback: $("personalityFeedback").value.trim() }),
    });
    $("personalityFeedback").value = "";
    renderSelected();
    toast("Ny personality-kandidat gemt. Den aktive person er uændret.");
  } catch (error) { toast(error.message, true); }
}

async function attachVoice() {
  if (!state.selected) return;
  const voicePackage = $("voiceLibrarySelect").value;
  if (!voicePackage) return toast("Vælg en VoiceRig-stemme først.", true);
  try {
    state.selected = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/voice/revisions`, {
      method: "POST",
      body: JSON.stringify({ voice_package: voicePackage, feedback: $("voiceFeedbackInput").value.trim() }),
    });
    $("voiceFeedbackInput").value = "";
    renderSelected();
    toast("VoiceRig-stemmen er gemt som hash-bundet kandidat. Den aktive person er uændret.");
  } catch (error) { toast(error.message, true); }
}

function useCandidate(kind, revisionId) {
  const select = $(`assemble${kind[0].toUpperCase()}${kind.slice(1)}`);
  if (select) select.value = revisionId;
  resetAssembly("Kandidatvalg ændret — kør audition igen.");
  switchTab("assemble");
}

async function prepareAssembly() {
  if (!state.selected) return;
  const body_revision = $("assembleBody").value;
  const voice_revision = $("assembleVoice").value;
  const personality_revision = $("assemblePersonality").value;
  const model = $("assemblyModel").value;
  const prompt = $("assemblyPrompt").value.trim();
  if (!body_revision || !voice_revision || !personality_revision) return toast("Vælg krop, stemme og personlighed.", true);
  if (!model) return toast("Vælg en ModelRig-model.", true);
  if (!prompt) return toast("Skriv en testprompt til personen.", true);

  resetAssembly("Validerer assembly og kører personality gennem ModelRig…");
  const key = selectedAuditionKey();
  try {
    const assembly = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/assembly`, {
      method: "POST",
      body: JSON.stringify({ body_revision, voice_revision, personality_revision }),
    });
    state.assembly = {
      key,
      fingerprint: assembly.assembly_fingerprint,
      auditionId: null,
      bodyLoaded: false,
      voiceHeard: false,
      personalityShown: true,
      replyShown: false,
    };
    $("assemblyFingerprint").textContent = `Assembly ${assembly.assembly_fingerprint.slice(0, 16)}… · kører ModelRig…`;
    $("assemblyPersonalityMeta").textContent = `${assembly.personality_preview.default_language} · ${assembly.personality_preview.style_notes || "ingen stilnote"}`;
    $("assemblyPersonalityText").textContent = assembly.personality_preview.instructions;
    $("assemblyPersonalityState").textContent = "Vist";
    $("assemblyPersonalityState").classList.remove("muted");
    $("assemblyBodyEmpty").classList.add("hidden");
    $("assemblyBodyPreview").classList.remove("hidden");
    $("assemblyBodyPreview").src = `${assembly.body_preview_url}&v=${encodeURIComponent(assembly.assembly_fingerprint)}`;

    const audition = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/auditions`, {
      method: "POST",
      body: JSON.stringify({ body_revision, voice_revision, personality_revision, model, prompt }),
    });
    if (!state.assembly || state.assembly.key !== key || selectedAuditionKey() !== key) {
      resetAssembly("Valget blev ændret under audition — kør igen.");
      return;
    }
    if (audition.assembly_fingerprint !== state.assembly.fingerprint) throw new Error("ModelRig-audition blev lavet mod en anden assembly.");
    state.assembly.auditionId = audition.audition_id;
    state.assembly.replyShown = true;
    $("assemblyReply").textContent = audition.reply;
    $("assemblyVoiceState").textContent = "Afspil hele ModelRig-svaret";
    $("assemblyVoiceState").classList.add("muted");
    $("assemblyVoiceAudio").src = `${audition.audio_url}?v=${encodeURIComponent(audition.audition_id)}`;
    $("assemblyVoiceAudio").load();
    $("assemblyFingerprint").textContent = `Assembly ${state.assembly.fingerprint.slice(0, 16)}… · ${audition.audition_id} · ${audition.model}`;
    updateAssemblyReadiness();
  } catch (error) {
    resetAssembly(`Audition fejlede: ${error.message}`);
    toast(error.message, true);
  }
}

async function approvePersonRevision() {
  if (!state.selected || !state.assembly) return;
  updateApprovalButton();
  if ($("approvePersonButton").disabled) return toast("Den samlede ModelRig/VoiceRig/body-audition og alle compatibility-kriterier skal være færdige først.", true);
  try {
    const payload = {
      body_revision: $("assembleBody").value,
      voice_revision: $("assembleVoice").value,
      personality_revision: $("assemblePersonality").value,
      assembly_fingerprint: state.assembly.fingerprint,
      audition_id: state.assembly.auditionId,
      body_voice_match: $("matchBodyVoice").checked,
      voice_personality_match: $("matchVoicePersonality").checked,
      body_personality_match: $("matchBodyPersonality").checked,
      overall_coherent: $("matchOverall").checked,
      compatibility_note: $("compatibilityNote").value.trim(),
      feedback: $("personRevisionFeedback").value.trim(),
      activate: true,
    };
    state.selected = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/revisions`, { method: "POST", body: JSON.stringify(payload) });
    const active = state.selected.active_person_revision;
    renderSelected();
    toast(`${active} er audition-bundet, godkendt og aktiv som samlet person.`);
  } catch (error) { toast(error.message, true); }
}

async function activatePersonRevision(revisionId) {
  if (!state.selected) return;
  try {
    state.selected = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/revisions/${encodeURIComponent(revisionId)}/activate`, { method: "POST" });
    renderSelected();
    toast(`${revisionId} er revalideret inklusive audition-evidence og aktiv som samlet person.`);
  } catch (error) { toast(error.message, true); }
}

async function proposeBodyChanges() {
  if (!state.selected) return;
  const feedback = $("bodyFeedback").value.trim();
  if (!feedback) return toast("Skriv først hvad du vil ændre.", true);
  try {
    const proposal = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/body/propose`, { method: "POST", body: JSON.stringify({ feedback }) });
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
    if (["failed", "canceled", "interrupted"].includes(job.status)) return toast(job.error || `Body-build ${job.status}`, true);
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
  if (name === "voice") loadVoiceLibrary();
  if (name === "assemble") loadModelLibrary();
}

function invalidateAudition(message) {
  if (state.assembly) resetAssembly(message);
}

function wire() {
  $("newPersonButton").addEventListener("click", openNewPerson);
  $("emptyCreateButton").addEventListener("click", openNewPerson);
  $("stashSearchButton").addEventListener("click", searchStash);
  $("stashSearchInput").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); searchStash(); } });
  $("createPersonButton").addEventListener("click", createPerson);
  $("savePersonalityButton").addEventListener("click", savePersonality);
  $("refreshVoicesButton").addEventListener("click", loadVoiceLibrary);
  $("attachVoiceButton").addEventListener("click", attachVoice);
  $("prepareAssemblyButton").addEventListener("click", prepareAssembly);
  $("approvePersonButton").addEventListener("click", approvePersonRevision);
  $("proposeBodyChanges").addEventListener("click", proposeBodyChanges);
  $("buildBodyButton").addEventListener("click", buildBody);
  for (const id of ["assembleBody", "assembleVoice", "assemblePersonality", "assemblyModel"]) {
    $(id).addEventListener("change", () => invalidateAudition("Kandidat eller model ændret — kør audition igen."));
  }
  $("assemblyPrompt").addEventListener("input", () => invalidateAudition("Testprompt ændret — kør audition igen."));
  for (const id of ["matchBodyVoice", "matchVoicePersonality", "matchBodyPersonality", "matchOverall"]) $(id).addEventListener("change", updateApprovalButton);
  $("compatibilityNote").addEventListener("input", updateApprovalButton);
  $("assemblyBodyPreview").addEventListener("load", () => {
    if (!state.assembly || state.assembly.key !== selectedAuditionKey()) return;
    state.assembly.bodyLoaded = true;
    $("assemblyBodyState").textContent = "Loadet";
    $("assemblyBodyState").classList.remove("muted");
    updateAssemblyReadiness();
  });
  $("assemblyBodyPreview").addEventListener("error", () => {
    if (!state.assembly) return;
    state.assembly.bodyLoaded = false;
    $("assemblyBodyState").textContent = "Preview-fejl";
    updateAssemblyReadiness();
  });
  $("assemblyVoiceAudio").addEventListener("ended", () => {
    if (!state.assembly || state.assembly.key !== selectedAuditionKey() || !state.assembly.auditionId) return;
    state.assembly.voiceHeard = true;
    $("assemblyVoiceState").textContent = "ModelRig-svar hørt til ende";
    $("assemblyVoiceState").classList.remove("muted");
    updateAssemblyReadiness();
  });
  document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => switchTab(button.dataset.tab)));
}

(async function start() {
  wire();
  resetAssembly();
  await health();
  loadVoiceLibrary();
  loadModelLibrary();
  try { await loadPeople(); } catch (error) { toast(error.message, true); }
})();
