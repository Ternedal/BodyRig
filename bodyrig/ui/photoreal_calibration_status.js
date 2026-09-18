(() => {
  let requestSerial = 0;
  let lastPersonId = "";

  function currentPersonId() {
    return (document.getElementById("personId")?.textContent || "").trim();
  }

  function ensureCard() {
    let card = document.getElementById("photorealCalibrationCard");
    if (card) return card;
    const tab = document.getElementById("tab-body");
    if (!tab) return null;

    card = document.createElement("article");
    card.id = "photorealCalibrationCard";
    card.className = "card space-top photoreal-calibration-card";
    card.innerHTML = `
      <div class="card-row photoreal-calibration-header">
        <div>
          <div class="card-label">Photoreal V2 · identity calibration</div>
          <div id="photorealCalibrationSummary" class="muted-text">Ingen calibration-status hentet.</div>
        </div>
        <div class="action-row photoreal-calibration-actions">
          <button id="photorealCalibrationRefresh" class="secondary" type="button">Opdatér</button>
          <button id="photorealCalibrationRun" class="primary" type="button" disabled>Kør diagnostic</button>
          <span id="photorealCalibrationBadge" class="badge muted">Ukendt</span>
        </div>
      </div>

      <div class="photoreal-calibration-grid">
        <section class="photoreal-calibration-panel">
          <div class="card-label">Run + Stage 13</div>
          <div id="photorealCalibrationRunMeta" class="photoreal-calibration-value">Ingen run</div>
          <div id="photorealCalibrationMargin" class="fine-print"></div>
          <div id="photorealCalibrationCounts" class="fine-print"></div>
          <div id="photorealCalibrationBlockers" class="photoreal-calibration-blockers"></div>
        </section>

        <section class="photoreal-calibration-panel">
          <div class="card-label">Collision diagnostic</div>
          <div id="photorealCalibrationCollision" class="photoreal-calibration-value">Ikke kørt.</div>
          <div id="photorealCalibrationGroupProfile" class="fine-print"></div>
          <div id="photorealCalibrationQuality" class="fine-print"></div>
        </section>
      </div>

      <section class="photoreal-calibration-panel space-top">
        <div class="card-row">
          <div>
            <div class="card-label">Stash-kontekst</div>
            <div id="photorealCalibrationStash" class="muted-text">Ingen Stash-data hentet.</div>
          </div>
          <span id="photorealCalibrationStashBadge" class="badge muted">Stash ukendt</span>
        </div>
        <div id="photorealCalibrationSources" class="photoreal-calibration-sources"></div>
      </section>

      <p class="fine-print photoreal-calibration-authority">
        Diagnosticen er read-only og kan ikke give identity matching, teacher training, photoreal acceptance eller production authority. Stash-data er kun kontekst og giver aldrig identity-authority.
      </p>
    `;

    const split = tab.querySelector(":scope > .split");
    if (split) split.insertAdjacentElement("afterend", card);
    else tab.prepend(card);

    document.getElementById("photorealCalibrationRefresh")?.addEventListener("click", () => {
      void refresh(true);
    });
    document.getElementById("photorealCalibrationRun")?.addEventListener("click", () => {
      void runDiagnostic();
    });
    return card;
  }

  function node(id) {
    ensureCard();
    return document.getElementById(id);
  }

  function formatNumber(value, digits = 6) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) : "—";
  }

  function formatDuration(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "—";
    const minutes = Math.floor(value / 60);
    const rest = Math.round(value % 60);
    return `${minutes}m ${rest}s`;
  }

  function clearSources() {
    const container = node("photorealCalibrationSources");
    if (container) container.replaceChildren();
  }

  function renderSources(sources) {
    const container = node("photorealCalibrationSources");
    if (!container) return;
    container.replaceChildren();
    const values = Array.isArray(sources) ? sources : [];
    if (!values.length) {
      const empty = document.createElement("div");
      empty.className = "fine-print";
      empty.textContent = "Ingen projection-safe lokale Stash-kilder i top-listen.";
      container.appendChild(empty);
      return;
    }
    for (const source of values) {
      const item = document.createElement("div");
      item.className = "photoreal-calibration-source";
      const top = document.createElement("div");
      top.className = "photoreal-calibration-source-top";
      const title = document.createElement("strong");
      title.textContent = source.scene_title || `Scene ${source.scene_id || "?"}`;
      const meta = document.createElement("span");
      meta.textContent = `${source.width || "?"}×${source.height || "?"} · ${formatDuration(source.duration)} · score ${formatNumber(source.score, 1)}`;
      top.append(title, meta);
      const path = document.createElement("code");
      path.textContent = source.path || "";
      item.append(top, path);
      container.appendChild(item);
    }
  }

  function reset(message) {
    const badge = node("photorealCalibrationBadge");
    node("photorealCalibrationSummary").textContent = message;
    badge.textContent = "Ukendt";
    badge.classList.add("muted");
    node("photorealCalibrationRunMeta").textContent = "Ingen run";
    node("photorealCalibrationMargin").textContent = "";
    node("photorealCalibrationCounts").textContent = "";
    node("photorealCalibrationBlockers").replaceChildren();
    node("photorealCalibrationCollision").textContent = "Ikke kørt.";
    node("photorealCalibrationGroupProfile").textContent = "";
    node("photorealCalibrationQuality").textContent = "";
    node("photorealCalibrationStash").textContent = "Ingen Stash-data hentet.";
    const stashBadge = node("photorealCalibrationStashBadge");
    stashBadge.textContent = "Stash ukendt";
    stashBadge.classList.add("muted");
    const runButton = node("photorealCalibrationRun");
    runButton.disabled = true;
    runButton.textContent = "Kør diagnostic";
    clearSources();
  }

  async function apiJson(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.headers || {}),
      },
      cache: "no-store",
    });
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    if (!response.ok) {
      const detail = payload && typeof payload.detail === "string"
        ? payload.detail
        : `HTTP ${response.status}`;
      throw new Error(detail);
    }
    return payload;
  }

  function renderBlockers(blockers) {
    const container = node("photorealCalibrationBlockers");
    container.replaceChildren();
    const values = Array.isArray(blockers) ? blockers : [];
    if (!values.length) return;
    for (const blocker of values) {
      const item = document.createElement("div");
      item.className = "photoreal-calibration-blocker";
      item.textContent = blocker;
      container.appendChild(item);
    }
  }

  function renderStash(stash) {
    const summary = node("photorealCalibrationStash");
    const badge = node("photorealCalibrationStashBadge");
    if (!stash || stash.available !== true) {
      summary.textContent = stash?.reason || "Stash er ikke tilgængelig.";
      badge.textContent = "Stash offline";
      badge.classList.add("muted");
      clearSources();
      return;
    }

    const performer = stash.performer || {};
    const truncation = stash.scene_count_may_be_truncated ? "+" : "";
    summary.textContent =
      `${performer.name || "Ukendt performer"} · id ${performer.id || "?"} · Stash ${stash.version || "?"} · ` +
      `${stash.scene_count_observed ?? 0}${truncation} scener · ${stash.single_performer_scene_count ?? 0} solo · ` +
      `${stash.multi_performer_scene_count ?? 0} multi · ${stash.four_k_file_count_observed ?? 0} 4K-filer.`;
    badge.textContent = "Stash live";
    badge.classList.remove("muted");
    renderSources(stash.top_local_sources);
  }

  function renderDiagnostic(diagnostic) {
    if (!diagnostic || typeof diagnostic !== "object") {
      node("photorealCalibrationCollision").textContent = "Diagnostic er ikke kørt endnu.";
      node("photorealCalibrationGroupProfile").textContent = "";
      node("photorealCalibrationQuality").textContent = "";
      return;
    }

    const highest = diagnostic.highest_negative_match || {};
    const performer = [highest.subject_performer_id, highest.subject_performer_name]
      .filter(Boolean)
      .join(" · ");
    const timestamp = highest.timestamp_seconds == null
      ? "stillbillede"
      : `${formatNumber(highest.timestamp_seconds, 3)} s`;
    node("photorealCalibrationCollision").textContent =
      `${performer || "Ukendt negativ performer"} · cosine ${formatNumber(highest.cosine, 6)} · ${timestamp}\n${highest.resolved_path || "Ingen verified source-path"}`;

    const group = highest.closest_positive_group || {};
    const reference = highest.closest_positive_reference || {};
    const groupText = group.group_id
      ? `Nærmeste positive group ${group.group_id}: ${formatNumber(group.cosine, 6)} · margin til næste ${formatNumber(highest.closest_positive_group_margin, 6)}.`
      : "Ingen positiv group-profil.";
    const referenceText = reference.group_id
      ? ` Nærmeste reference: group ${reference.group_id}, source ${reference.source_key || "?"}, cosine ${formatNumber(reference.cosine, 6)}.`
      : "";
    node("photorealCalibrationGroupProfile").textContent = groupText + referenceText;

    const quality = diagnostic.negative_observation_quality_metadata || {};
    const collisionQuality = highest.quality_metadata || {};
    const collisionQualityText = highest.quality_metadata_complete === true
      ? (
          `Collision-frame quality: candidate ${collisionQuality.candidate_id || "?"} · count ${collisionQuality.candidate_count ?? "?"} · ` +
          `view ${collisionQuality.view_bin || "?"} · face ${formatNumber(collisionQuality.face_visibility, 2)} · ` +
          `body ${formatNumber(collisionQuality.full_body_visibility, 2)} · occupancy ${formatNumber(collisionQuality.person_fraction, 2)} · ` +
          `sharpness ${formatNumber(collisionQuality.sharpness, 2)} · motion ${formatNumber(collisionQuality.motion, 2)} · ` +
          `occlusion ${formatNumber(collisionQuality.occlusion, 2)}.`
        )
      : "Collision-frame quality: ikke tilgængelig i denne gemte observation.";
    if (quality.complete_quality_audit_available === true) {
      node("photorealCalibrationQuality").textContent =
        collisionQualityText + " " +
        `Quality-audit tilgængelig: ${quality.complete_observation_count ?? 0}/${diagnostic.negative_observation_count ?? 0} observations har komplet metadata.`;
    } else {
      const missing = Array.isArray(quality.missing_fields) ? quality.missing_fields.join(", ") : "ukendte felter";
      node("photorealCalibrationQuality").textContent =
        collisionQualityText + " " +
        `Quality-audit kræver re-extraction: ${quality.complete_observation_count ?? 0}/${diagnostic.negative_observation_count ?? 0} komplette observations. Mangler: ${missing}.`;
    }
  }

  function render(value) {
    const badge = node("photorealCalibrationBadge");
    const runButton = node("photorealCalibrationRun");
    const performer = value.performer || {};

    if (value.state === "unbound") {
      reset(value.message || "Personen er ikke bundet til Stash.");
      badge.textContent = "Ikke bundet";
      renderStash(value.stash);
      return;
    }

    if (value.state === "no-run" || !value.run) {
      reset(`${performer.name || "Performer"} · ${value.message || "Ingen Photoreal-run."}`);
      badge.textContent = "Ingen run";
      renderStash(value.stash);
      return;
    }

    const run = value.run;
    const stage = run.stage13 || {};
    const stageState = stage.state || "not-run";
    const blocked = stageState === "blocked";
    const passed = stageState === "pass";
    badge.textContent = blocked ? "Stage 13 BLOCKED" : (passed ? "Stage 13 PASS" : "Stage 13 ikke kørt");
    badge.classList.toggle("muted", !passed);

    node("photorealCalibrationSummary").textContent =
      `${performer.name || "Performer"} · Stash id ${performer.id || "?"} · ${run.name}`;
    node("photorealCalibrationRunMeta").textContent =
      `${run.modified_utc || "ukendt tid"}\n${run.path || ""}`;

    if (stage.available === true) {
      node("photorealCalibrationMargin").textContent =
        `Separation: ${formatNumber(stage.observed_separation_margin, 6)} · krav ≥ ${formatNumber(stage.minimum_required_separation_margin, 6)} · positive floor ${formatNumber(stage.positive_floor, 6)} · negative ceiling ${formatNumber(stage.negative_ceiling, 6)}.`;
      node("photorealCalibrationCounts").textContent =
        `Positive refs/groups: ${stage.positive_reference_count ?? "?"}/${stage.positive_group_count ?? "?"} · negatives: ${stage.negative_observation_count ?? "?"} observations / ${stage.negative_performer_count ?? "?"} performers.`;
      renderBlockers(stage.blockers);
    } else {
      node("photorealCalibrationMargin").textContent = stage.message || "Stage 13 artifact mangler.";
      node("photorealCalibrationCounts").textContent = "";
      renderBlockers([]);
    }

    renderDiagnostic(run.diagnostic);
    renderStash(value.stash);

    runButton.disabled = run.diagnostic_ready !== true || run.diagnostic_available === true;
    runButton.textContent = run.diagnostic_available === true ? "Diagnostic klar" : "Kør diagnostic";
    if (run.diagnostic_ready !== true && Array.isArray(run.diagnostic_missing_artifacts)) {
      node("photorealCalibrationQuality").textContent =
        `Diagnostic kan ikke køres endnu. Mangler: ${run.diagnostic_missing_artifacts.join(", ")}.`;
    }
  }

  async function refresh(force = false) {
    ensureCard();
    const personId = currentPersonId();
    if (!personId) return reset("Ingen person valgt.");
    if (!force && personId === lastPersonId) return;
    lastPersonId = personId;
    const serial = ++requestSerial;

    node("photorealCalibrationSummary").textContent = "Henter calibration-status og Stash-kontekst…";
    try {
      const value = await apiJson(
        `/api/v1/people/${encodeURIComponent(personId)}/body/photoreal-calibration`
      );
      if (serial !== requestSerial || currentPersonId() !== personId) return;
      render(value);
    } catch (error) {
      if (serial !== requestSerial) return;
      reset(`Fail-closed: ${error.message}`);
    }
  }

  async function runDiagnostic() {
    const personId = currentPersonId();
    if (!personId) return;
    const button = node("photorealCalibrationRun");
    button.disabled = true;
    button.textContent = "Kører…";
    try {
      const value = await apiJson(
        `/api/v1/people/${encodeURIComponent(personId)}/body/photoreal-calibration/diagnostic`,
        { method: "POST" }
      );
      if (currentPersonId() !== personId) return;
      render(value);
    } catch (error) {
      button.textContent = "Kør diagnostic";
      node("photorealCalibrationSummary").textContent = `Diagnostic fejlede: ${error.message}`;
      void refresh(true);
    }
  }

  const personNode = document.getElementById("personId");
  if (personNode) {
    new MutationObserver(() => {
      lastPersonId = "";
      void refresh(true);
    }).observe(personNode, {
      childList: true,
      characterData: true,
      subtree: true,
    });
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) void refresh(true);
  });

  ensureCard();
  void refresh(true);
})();
