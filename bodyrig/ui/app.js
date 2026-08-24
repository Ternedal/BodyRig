const state = { people: [], selected: null, selectedStash: null, tab: "overview" };

const $ = (id) => document.getElementById(id);

function toast(message, error = false) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("error", error);
  el.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.add("hidden"), 3600);
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

function revisionById(profile, kind, id) {
  return (profile[`${kind}_revisions`] || []).find((item) => item.revision_id === id) || null;
}

function short(value, n = 28) {
  if (!value) return "—";
  return value.length > n ? `${value.slice(0, n - 1)}…` : value;
}

function renderPeople() {
  const list = $("personList");
  list.innerHTML = "";
  for (const person of state.people) {
    const button = document.createElement("button");
    button.className = `person-item${state.selected?.person_id === person.person_id ? " active" : ""}`;
    button.innerHTML = `<strong>${escapeHtml(person.display_name)}</strong><span>${escapeHtml(person.source?.performer_name || "Lokal profil")}</span>`;
    button.addEventListener("click", () => selectPerson(person.person_id));
    list.appendChild(button);
  }
}

function renderRevisionList(targetId, profile, kind, labelField) {
  const target = $(targetId);
  const items = profile[`${kind}_revisions`] || [];
  const active = profile.active?.[`${kind}_revision`] || null;
  target.innerHTML = "";
  if (!items.length) {
    target.innerHTML = `<div class="muted-text">Ingen ${kind}-revisioner endnu.</div>`;
    return;
  }
  [...items].reverse().forEach((item) => {
    const row = document.createElement("div");
    row.className = `revision-item${item.revision_id === active ? " active" : ""}`;
    const feedback = item.feedback ? `<div class="revision-feedback">${escapeHtml(item.feedback)}</div>` : "";
    row.innerHTML = `
      <div class="revision-top">
        <div><div class="revision-id">${escapeHtml(item.revision_id)}</div><div class="revision-meta">${escapeHtml(item[labelField] || "")}</div></div>
        ${item.revision_id === active ? '<span class="badge">Aktiv</span>' : `<button class="secondary activate-revision" data-kind="${kind}" data-revision="${item.revision_id}">Aktivér</button>`}
      </div>${feedback}`;
    target.appendChild(row);
  });
  target.querySelectorAll(".activate-revision").forEach((button) => {
    button.addEventListener("click", () => activateRevision(button.dataset.kind, button.dataset.revision));
  });
}

function renderHistory(profile) {
  const target = $("historyList");
  const all = [];
  for (const kind of ["body", "voice", "personality"]) {
    for (const item of profile[`${kind}_revisions`] || []) all.push({ ...item, kind });
  }
  all.sort((a, b) => String(b.created_utc).localeCompare(String(a.created_utc)));
  target.innerHTML = "";
  if (!all.length) {
    target.innerHTML = '<div class="muted-text">Ingen revisioner endnu.</div>';
    return;
  }
  for (const item of all) {
    const row = document.createElement("div");
    row.className = "revision-item";
    const title = item.kind === "body" ? item.body_id : item.kind === "voice" ? item.voice_id : short(item.instructions, 80);
    row.innerHTML = `<div class="revision-top"><div><div class="revision-id">${escapeHtml(item.revision_id)}</div><div class="revision-meta">${escapeHtml(title || "")}</div></div><span class="badge muted">${escapeHtml(item.kind)}</span></div>${item.feedback ? `<div class="revision-feedback">${escapeHtml(item.feedback)}</div>` : ""}`;
    target.appendChild(row);
  }
}

function renderSelected() {
  const p = state.selected;
  $("emptyState").classList.toggle("hidden", Boolean(p));
  $("personView").classList.toggle("hidden", !p);
  renderPeople();
  if (!p) return;

  $("personId").textContent = p.person_id;
  $("personName").textContent = p.display_name;
  $("personSource").textContent = p.source ? `Stash: ${p.source.performer_name} · id ${p.source.performer_id}` : "Ingen Stash-binding";

  const body = revisionById(p, "body", p.active.body_revision);
  const voice = revisionById(p, "voice", p.active.voice_revision);
  const personality = revisionById(p, "personality", p.active.personality_revision);
  $("bodyActive").textContent = `Krop ${p.active.body_revision || "—"}`;
  $("voiceActive").textContent = `Stemme ${p.active.voice_revision || "—"}`;
  $("personalityActive").textContent = `Personlighed ${p.active.personality_revision || "—"}`;
  $("overviewBody").textContent = p.active.body_revision || "Ingen";
  $("overviewVoice").textContent = p.active.voice_revision || "Ingen";
  $("overviewPersonality").textContent = p.active.personality_revision || "Ingen";

  $("buildSourceText").textContent = p.source ? `Klar til build fra ${p.source.performer_name} (Stash id ${p.source.performer_id}).` : "Bind personen til en Stash performer først.";
  $("buildBodyButton").disabled = !p.source;
  $("bodyCount").textContent = String(p.body_revisions.length);
  renderRevisionList("bodyRevisions", p, "body", "body_id");
  renderRevisionList("voiceRevisions", p, "voice", "voice_id");
  renderRevisionList("personalityRevisions", p, "personality", "default_language");
  renderHistory(p);

  $("bodyRevisionLabel").textContent = p.active.body_revision || "Ingen revision";
  $("previewEmpty").classList.toggle("hidden", Boolean(body));
  $("bodyPreview").classList.toggle("hidden", !body);
  if (body) {
    $("bodyPreview").src = `/api/v1/people/${encodeURIComponent(p.person_id)}/body/preview?revision=${encodeURIComponent(body.revision_id)}&v=${encodeURIComponent(body.package_sha256)}`;
  } else {
    $("bodyPreview").removeAttribute("src");
  }

  if (personality) {
    $("personalityInstructions").value = personality.instructions;
    $("personalityLanguage").value = personality.default_language;
    $("personalityStyle").value = personality.style_notes || "";
  } else {
    $("personalityInstructions").value = "";
    $("personalityLanguage").value = "da";
    $("personalityStyle").value = "";
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[ch]));
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
    const updated = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/personality/revisions`, {
      method: "POST",
      body: JSON.stringify({
        instructions,
        default_language: $("personalityLanguage").value.trim() || "da",
        style_notes: $("personalityStyle").value.trim(),
        feedback: $("personalityFeedback").value.trim(),
        activate: true,
      }),
    });
    state.selected = updated;
    $("personalityFeedback").value = "";
    renderSelected();
    toast("Ny personality-revision gemt og aktiveret.");
  } catch (error) { toast(error.message, true); }
}

async function attachVoice() {
  if (!state.selected) return;
  const voiceId = $("voiceIdInput").value.trim();
  if (!voiceId) { toast("Voice ID mangler.", true); return; }
  try {
    const updated = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/voice/revisions`, {
      method: "POST",
      body: JSON.stringify({
        voice_id: voiceId,
        package_path: $("voicePathInput").value.trim() || null,
        feedback: $("voiceFeedbackInput").value.trim(),
        activate: true,
      }),
    });
    state.selected = updated;
    $("voiceFeedbackInput").value = "";
    renderSelected();
    toast("Voice-revision gemt og aktiveret.");
  } catch (error) { toast(error.message, true); }
}

async function activateRevision(kind, revisionId) {
  if (!state.selected) return;
  try {
    state.selected = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/activate/${encodeURIComponent(kind)}/${encodeURIComponent(revisionId)}`, { method: "POST" });
    renderSelected();
    toast(`${revisionId} er nu aktiv.`);
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
      $("bodyProposal").textContent = "Ingen sikker struktureret ændring fundet. Kommentaren er bevaret, men BodyRig ændrer ikke noget på et gæt.";
      return;
    }
    $("bodyProposal").innerHTML = `<strong>Forslag — ikke anvendt endnu</strong>\n${proposal.changes.map((c) => `${c.field}: ${c.delta > 0 ? "+" : ""}${c.delta}`).join("\n")}`;
  } catch (error) { toast(error.message, true); }
}

async function buildBody() {
  if (!state.selected?.source) return;
  try {
    const result = await api(`/api/v1/people/${encodeURIComponent(state.selected.person_id)}/body/build`, { method: "POST", body: JSON.stringify({}) });
    toast(`Body-build startet: ${result.job_id}`);
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
  $("proposeBodyChanges").addEventListener("click", proposeBodyChanges);
  $("buildBodyButton").addEventListener("click", buildBody);
  document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => switchTab(button.dataset.tab)));
}

(async function start() {
  wire();
  await health();
  try { await loadPeople(); } catch (error) { toast(error.message, true); }
})();
