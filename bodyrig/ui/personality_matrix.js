(() => {
  const NS = "http://www.w3.org/2000/svg";
  const SIZE = 760;
  const CENTER = SIZE / 2;
  const RADIUS = 270;
  const LABEL_RADIUS = 318;
  const LABEL_LIMIT = 14;
  const NEUTRAL = 0.5;
  const EPSILON = 0.000001;

  const state = {
    ring: "inner",
    selectedId: null,
    baselineKey: null,
    baselineRevision: null,
    baselineStatus: "idle",
    baselineBlueprint: null,
    rawVisible: false,
    scheduled: false,
    dragTraitId: null,
    dragPointerId: null,
  };

  const $ = id => document.getElementById(id);

  function svgEl(name, attrs = {}) {
    const node = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    return node;
  }

  function traitEntries(ring = state.ring) {
    const container = $(ring === "inner" ? "innerTraits" : "outerTraits");
    if (!container) return [];
    const prefix = `trait-${ring}-`;
    const entries = [];
    for (const row of container.querySelectorAll(".trait-slider-row")) {
      const input = row.querySelector('input[type="range"]');
      const label = row.querySelector("label");
      if (!input || !label || !input.id.startsWith(prefix)) continue;
      const value = Number(input.value);
      if (!Number.isFinite(value)) continue;
      entries.push({
        ring,
        traitId: input.id.slice(prefix.length),
        input,
        label: label.textContent.trim(),
        value,
      });
    }
    return entries;
  }

  function baselineSelection() {
    const personId = $("personSelect")?.value || "";
    const revision = $("matrixCompareRevision")?.value || "";
    if (!personId || !revision) return null;
    return { personId, revision, key: `${personId}|${revision}` };
  }

  function syncCompareOptions() {
    const source = $("baselineRevision");
    const target = $("matrixCompareRevision");
    if (!source || !target) return;

    const previous = target.value;
    const editingRevision = new URLSearchParams(location.search).get("edit_revision") || "";
    const matrixOptions = [...source.options].filter(
      option => option.value && option.textContent.includes("Matrix v2")
    );

    target.replaceChildren();
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = matrixOptions.some(option => option.value !== editingRevision)
      ? "Ingen sammenligning"
      : "Ingen tidligere Matrix v2-revisioner";
    target.appendChild(empty);

    for (const sourceOption of matrixOptions) {
      const option = document.createElement("option");
      option.value = sourceOption.value;
      option.textContent = sourceOption.textContent;
      target.appendChild(option);
    }

    const values = new Set(matrixOptions.map(option => option.value));
    const previousStillComparable = previous && previous !== editingRevision && values.has(previous);
    const fallback = [...matrixOptions].reverse().find(option => option.value !== editingRevision);
    target.value = previousStillComparable ? previous : (fallback?.value || "");

    if (target.value !== previous) {
      document.dispatchEvent(new CustomEvent("bodyrig:matrix-compare-change"));
    }
  }

  function validMatrixBlueprint(value) {
    return Boolean(
      value &&
      value.version === 2 &&
      value.inner_ring &&
      typeof value.inner_ring === "object" &&
      Object.keys(value.inner_ring).length === 60 &&
      value.outer_ring &&
      typeof value.outer_ring === "object" &&
      Object.keys(value.outer_ring).length === 60
    );
  }

  async function loadBaselineIfNeeded() {
    const selection = baselineSelection();
    if (!selection) {
      if (state.baselineKey !== null || state.baselineStatus !== "idle") {
        state.baselineKey = null;
        state.baselineRevision = null;
        state.baselineStatus = "idle";
        state.baselineBlueprint = null;
        scheduleRender();
      }
      return;
    }
    if (selection.key === state.baselineKey) return;

    state.baselineKey = selection.key;
    state.baselineRevision = selection.revision;
    state.baselineStatus = "loading";
    state.baselineBlueprint = null;
    scheduleRender();

    try {
      const response = await fetch(
        `/api/v1/people/${encodeURIComponent(selection.personId)}/personality/guided/revisions/${encodeURIComponent(selection.revision)}`
      );
      if (state.baselineKey !== selection.key) return;
      if (!response.ok) {
        state.baselineStatus = "unavailable";
        scheduleRender();
        return;
      }
      const source = await response.json();
      if (state.baselineKey !== selection.key) return;
      if (!validMatrixBlueprint(source?.blueprint)) {
        state.baselineStatus = "unavailable";
        scheduleRender();
        return;
      }
      state.baselineStatus = "ready";
      state.baselineBlueprint = source.blueprint;
      scheduleRender();
    } catch (_error) {
      if (state.baselineKey !== selection.key) return;
      state.baselineStatus = "unavailable";
      state.baselineBlueprint = null;
      scheduleRender();
    }
  }

  function baselineValue(entry) {
    if (state.baselineStatus !== "ready" || !state.baselineBlueprint) return null;
    const value = Number(state.baselineBlueprint[`${entry.ring}_ring`]?.[entry.traitId]);
    return Number.isFinite(value) ? value : null;
  }

  function ensureUi() {
    let cockpit = $("personalityMatrixCockpit");
    if (cockpit) return cockpit;
    const changeSummary = $("traitChangeSummary");
    if (!changeSummary) return null;

    cockpit = document.createElement("section");
    cockpit.id = "personalityMatrixCockpit";
    cockpit.className = "matrix-cockpit";
    cockpit.innerHTML = `
      <div class="matrix-cockpit-head">
        <div>
          <div class="eyebrow">PERSONALITY MATRIX V2 · RADIAL EDITOR</div>
          <h2 class="matrix-cockpit-title">Authored personality shape</h2>
          <p class="matrix-cockpit-copy">Grafen er en deterministisk editor af de 120 authored Matrix-værdier. Klik et punkt for at inspicere det, eller træk punktet radialt for at ændre den præcise trait.</p>
        </div>
        <div class="matrix-head-controls">
          <label class="matrix-compare-control" for="matrixCompareRevision">
            <span>Sammenlign med</span>
            <select id="matrixCompareRevision"><option value="">Ingen sammenligning</option></select>
          </label>
          <div class="matrix-ring-tabs" role="tablist" aria-label="Personality Matrix ring">
            <button class="matrix-ring-tab active" type="button" data-ring="inner" role="tab" aria-selected="true">Inner · 60</button>
            <button class="matrix-ring-tab" type="button" data-ring="outer" role="tab" aria-selected="false">Outer · 60</button>
          </div>
        </div>
      </div>
      <div class="matrix-stage">
        <div class="matrix-plot-wrap">
          <svg id="personalityMatrixSvg" class="matrix-svg" viewBox="0 0 760 760" role="img" aria-label="Radial visualisering af authored personality traits"></svg>
        </div>
        <aside id="matrixInspector" class="matrix-inspector" aria-live="polite">
          <div class="matrix-inspector-kicker">Selected trait</div>
          <h3 id="matrixInspectorName">—</h3>
          <div id="matrixInspectorMeta" class="matrix-inspector-meta">Vælg et punkt i matrixen.</div>
          <div class="matrix-inspector-value"><strong id="matrixInspectorValue">0.50</strong><span>authored</span></div>
          <input id="matrixInspectorRange" type="range" min="0" max="1" step="0.05" value="0.5" aria-label="Redigér valgt personality trait">
          <div class="matrix-scale"><span>0.00</span><span>neutral 0.50</span><span>1.00</span></div>
          <div id="matrixBaselineReadout" class="matrix-baseline-readout">Vælg en Matrix v2-baseline for at se delta.</div>
          <div class="matrix-inspector-actions">
            <button id="matrixNeutralButton" class="secondary" type="button">Sæt til neutral · 0.50</button>
            <button id="matrixJumpButton" class="secondary" type="button">Vis rå slider</button>
          </div>
          <div class="matrix-save-panel">
            <div class="matrix-save-copy">
              <div id="matrixSaveState" class="matrix-save-state" data-state="dirty">Ikke gemt</div>
              <div id="matrixSaveNote" class="matrix-save-note">Byg preview før du gemmer en ny immutable personality-revision.</div>
            </div>
            <div class="matrix-save-actions">
              <button id="matrixPreviewButton" class="secondary" type="button">Byg preview</button>
              <button id="matrixSaveButton" class="primary" type="button" disabled>Gem revision</button>
              <a id="matrixAuditionLink" class="secondary matrix-audition-link" href="/ui/personality_audition_suite.html" hidden>Test denne revision · 6 scenarier</a>
            </div>
          </div>
        </aside>
      </div>
      <div id="matrixStatus" class="matrix-status"></div>
      <div class="matrix-footer">
        <div class="matrix-legend">
          <span class="matrix-legend-item"><i class="matrix-legend-swatch"></i>Current authored</span>
          <span class="matrix-legend-item"><i class="matrix-legend-swatch baseline"></i>Valgt Matrix v2 baseline</span>
          <span class="matrix-legend-item"><i class="matrix-legend-swatch neutral"></i>Neutral · 0.50</span>
        </div>
        <button id="matrixRawToggle" class="secondary matrix-raw-toggle" type="button">Vis rå 120 sliders</button>
      </div>
    `;

    const tools = document.querySelector(".trait-tools");
    if (tools) tools.insertAdjacentElement("beforebegin", cockpit);
    else changeSummary.insertAdjacentElement("afterend", cockpit);

    document.body.classList.add("matrix-raw-hidden");
    syncCompareOptions();
    $("matrixCompareRevision")?.addEventListener("change", () => {
      state.baselineKey = null;
      state.baselineRevision = null;
      state.baselineStatus = "idle";
      state.baselineBlueprint = null;
      document.dispatchEvent(new CustomEvent("bodyrig:matrix-compare-change"));
      scheduleRender();
    });

    cockpit.querySelectorAll(".matrix-ring-tab").forEach(button => {
      button.addEventListener("click", () => {
        state.ring = button.dataset.ring === "outer" ? "outer" : "inner";
        state.selectedId = null;
        cockpit.querySelectorAll(".matrix-ring-tab").forEach(other => {
          const active = other === button;
          other.classList.toggle("active", active);
          other.setAttribute("aria-selected", active ? "true" : "false");
        });
        scheduleRender();
      });
    });

    const svg = $("personalityMatrixSvg");
    svg?.addEventListener("pointerdown", event => {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      const node = event.target.closest?.(".matrix-node");
      if (!node) return;
      const traitId = node.getAttribute("data-trait-id");
      if (!traitId) return;
      state.selectedId = traitId;
      state.dragTraitId = traitId;
      state.dragPointerId = event.pointerId;
      svg.setPointerCapture?.(event.pointerId);
      svg.classList.add("dragging");
      event.preventDefault();
      updateDraggedTrait(svg, event);
    });
    svg?.addEventListener("pointermove", event => {
      if (state.dragPointerId !== event.pointerId || !state.dragTraitId) return;
      event.preventDefault();
      updateDraggedTrait(svg, event);
    });
    const endDrag = event => {
      if (state.dragPointerId !== event.pointerId) return;
      state.dragTraitId = null;
      state.dragPointerId = null;
      svg?.classList.remove("dragging");
      if (svg?.hasPointerCapture?.(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    };
    svg?.addEventListener("pointerup", endDrag);
    svg?.addEventListener("pointercancel", endDrag);

    $("matrixInspectorRange")?.addEventListener("input", event => {
      const entry = selectedEntry();
      if (!entry) return;
      const value = Number(event.target.value);
      if (!Number.isFinite(value)) return;
      writeTraitValue(entry, value);
    });

    $("matrixNeutralButton")?.addEventListener("click", () => setSelectedValue(NEUTRAL));
    $("matrixJumpButton")?.addEventListener("click", jumpToRawSlider);
    $("matrixRawToggle")?.addEventListener("click", toggleRawControls);
    $("matrixPreviewButton")?.addEventListener("click", () => $("previewButton")?.click());
    $("matrixSaveButton")?.addEventListener("click", () => $("saveButton")?.click());
    syncSaveControls();

    return cockpit;
  }

  function syncSaveControls() {
    const sourcePreview = $("previewButton");
    const sourceSave = $("saveButton");
    const mirrorPreview = $("matrixPreviewButton");
    const mirrorSave = $("matrixSaveButton");
    const stateTarget = $("matrixSaveState");
    const noteTarget = $("matrixSaveNote");
    if (!sourcePreview || !sourceSave || !mirrorPreview || !mirrorSave || !stateTarget || !noteTarget) return;

    mirrorPreview.disabled = sourcePreview.disabled;
    mirrorSave.disabled = sourceSave.disabled;

    const status = $("status")?.textContent?.trim() || "";
    const blueprint = $("blueprintBadge")?.textContent?.trim() || "";
    let stateName = "dirty";
    let stateText = "Ikke gemt";
    let noteText = "Byg preview før du gemmer en ny immutable personality-revision.";

    if (/Gemmer immutable/i.test(status)) {
      stateName = "saving";
      stateText = "Gemmer…";
      noteText = status;
    } else if (!sourceSave.disabled || /Preview klar/i.test(status)) {
      stateName = "ready";
      stateText = "Preview klar";
      noteText = "Preview er verificeret for de aktuelle værdier. Gem revision for at persistere dem.";
    } else if (/Preview forældet/i.test(blueprint)) {
      stateName = "dirty";
      stateText = "Ikke gemte ændringer";
      noteText = "Matrixen er ændret siden sidste preview. Byg preview igen før gem.";
    } else if (/gemt · blueprint/i.test(status) || /genindlæst fra verificeret blueprint/i.test(status)) {
      stateName = "saved";
      stateText = "Gemt";
      noteText = status;
    } else if (status) {
      noteText = status;
    }

    const previewPrimary = stateName === "dirty";
    const savePrimary = stateName === "ready";
    mirrorPreview.classList.toggle("primary", previewPrimary);
    mirrorPreview.classList.toggle("secondary", !previewPrimary);
    mirrorSave.classList.toggle("primary", savePrimary);
    mirrorSave.classList.toggle("secondary", !savePrimary);

    const auditionLink = $("matrixAuditionLink");
    if (auditionLink) {
      const personId = $("personSelect")?.value || "";
      const revision = new URLSearchParams(location.search).get("edit_revision") || "";
      const revisionExists = [...($("baselineRevision")?.options || [])].some(
        option => option.value === revision
      );
      const auditionReady = stateName === "saved" && Boolean(personId && revision && revisionExists);
      auditionLink.hidden = !auditionReady;
      auditionLink.href = auditionReady
        ? `/ui/personality_audition_suite.html?person_id=${encodeURIComponent(personId)}&personality_revision=${encodeURIComponent(revision)}`
        : "/ui/personality_audition_suite.html";
    }

    stateTarget.dataset.state = stateName;
    stateTarget.textContent = stateText;
    noteTarget.textContent = noteText;
  }

  function selectedEntry() {
    const entries = traitEntries();
    return entries.find(entry => entry.traitId === state.selectedId) || null;
  }

  function writeTraitValue(entry, nextValue) {
    if (!entry) return;
    const clamped = Math.max(0, Math.min(1, Number(nextValue)));
    if (!Number.isFinite(clamped)) return;
    const snapped = Math.round(clamped / 0.05) * 0.05;
    entry.input.value = snapped.toFixed(2);
    entry.input.dispatchEvent(new Event("input", { bubbles: true }));
    scheduleRender();
  }

  function updateDraggedTrait(svg, event) {
    const entries = traitEntries();
    const index = entries.findIndex(entry => entry.traitId === state.dragTraitId);
    if (index < 0) return;
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = (event.clientX - rect.left) * (SIZE / rect.width);
    const y = (event.clientY - rect.top) * (SIZE / rect.height);
    const angle = -Math.PI / 2 + (Math.PI * 2 * index) / entries.length;
    const axisX = Math.cos(angle);
    const axisY = Math.sin(angle);
    const projected = ((x - CENTER) * axisX + (y - CENTER) * axisY) / RADIUS;
    state.selectedId = entries[index].traitId;
    writeTraitValue(entries[index], projected);
  }

  function signatureScore(entry) {
    const base = baselineValue(entry);
    return Math.max(
      Math.abs(entry.value - NEUTRAL),
      base === null ? 0 : Math.abs(entry.value - base)
    );
  }

  function ensureSelection(entries) {
    if (!entries.length) {
      state.selectedId = null;
      return null;
    }
    const current = entries.find(entry => entry.traitId === state.selectedId);
    if (current) return current;

    const maxScore = entries.reduce((max, entry) => Math.max(max, signatureScore(entry)), 0);
    if (maxScore <= EPSILON) {
      state.selectedId = entries[0].traitId;
      return entries[0];
    }

    const ranked = [...entries].sort(
      (a, b) => signatureScore(b) - signatureScore(a) || a.label.localeCompare(b.label, "da")
    );
    state.selectedId = ranked[0].traitId;
    return ranked[0];
  }

  function pointFor(index, total, value, radius = RADIUS) {
    const angle = -Math.PI / 2 + (Math.PI * 2 * index) / total;
    return {
      angle,
      x: CENTER + Math.cos(angle) * radius * value,
      y: CENTER + Math.sin(angle) * radius * value,
    };
  }

  function polygonPoints(entries, valueFor) {
    return entries.map((entry, index) => {
      const value = Math.max(0, Math.min(1, Number(valueFor(entry)) || 0));
      const point = pointFor(index, entries.length, value);
      return `${point.x.toFixed(2)},${point.y.toFixed(2)}`;
    }).join(" ");
  }

  function circularIndexDistance(left, right, total) {
    const direct = Math.abs(left - right);
    return Math.min(direct, total - direct);
  }

  function labelledEntries(entries, selected) {
    const scored = entries.map((entry, index) => ({ entry, index, score: signatureScore(entry) }));
    const maxScore = scored.reduce((max, item) => Math.max(max, item.score), 0);
    let selectedIndexes;

    if (maxScore <= EPSILON) {
      selectedIndexes = new Set();
      for (let slot = 0; slot < LABEL_LIMIT; slot += 1) {
        selectedIndexes.add(Math.floor((slot * entries.length) / LABEL_LIMIT) % entries.length);
      }
    } else {
      const ranked = [...scored].sort(
        (a, b) => b.score - a.score || a.entry.label.localeCompare(b.entry.label, "da")
      );
      selectedIndexes = new Set();
      const minimumAxisGap = Math.max(2, Math.floor(entries.length / LABEL_LIMIT) - 1);
      for (const item of ranked) {
        if (selectedIndexes.size >= LABEL_LIMIT) break;
        const separated = [...selectedIndexes].every(
          index => circularIndexDistance(index, item.index, entries.length) >= minimumAxisGap
        );
        if (separated) selectedIndexes.add(item.index);
      }
    }

    if (selected) {
      const selectedIndex = entries.findIndex(entry => entry.traitId === selected.traitId);
      if (selectedIndex >= 0) selectedIndexes.add(selectedIndex);
    }

    return scored.filter(item => selectedIndexes.has(item.index));
  }

  function relaxedLabels(items) {
    const minY = 54;
    const maxY = SIZE - 66;
    const gap = 27;
    const sides = { left: [], right: [] };

    for (const item of items) {
      const edge = pointFor(item.index, item.total, 1, LABEL_RADIUS);
      const side = Math.cos(edge.angle) >= 0 ? "right" : "left";
      sides[side].push({ ...item, side, desiredY: edge.y, edge });
    }

    const result = [];
    for (const side of ["left", "right"]) {
      const list = sides[side].sort((a, b) => a.desiredY - b.desiredY);
      let cursor = minY;
      for (const item of list) {
        item.y = Math.max(cursor, Math.min(maxY, item.desiredY));
        cursor = item.y + gap;
      }
      if (list.length && list[list.length - 1].y > maxY) {
        let reverseCursor = maxY;
        for (let index = list.length - 1; index >= 0; index -= 1) {
          list[index].y = Math.min(list[index].y, reverseCursor);
          reverseCursor = list[index].y - gap;
        }
      }
      for (const item of list) {
        item.x = side === "right" ? SIZE - 62 : 62;
        result.push(item);
      }
    }
    return result;
  }

  function renderSvg(entries, selected) {
    const svg = $("personalityMatrixSvg");
    if (!svg) return;
    svg.replaceChildren();

    const title = svgEl("title");
    title.textContent = `${state.ring === "inner" ? "Inner" : "Outer"} Ring, 60 authored traits`;
    svg.appendChild(title);

    for (let step = 1; step <= 5; step += 1) {
      svg.appendChild(svgEl("circle", {
        cx: CENTER,
        cy: CENTER,
        r: (RADIUS * step) / 5,
        class: step === 5 ? "matrix-grid-circle" : "matrix-grid-circle",
      }));
    }
    svg.appendChild(svgEl("circle", {
      cx: CENTER,
      cy: CENTER,
      r: RADIUS * NEUTRAL,
      class: "matrix-neutral-circle",
    }));

    entries.forEach((entry, index) => {
      const outer = pointFor(index, entries.length, 1);
      svg.appendChild(svgEl("line", {
        x1: CENTER,
        y1: CENTER,
        x2: outer.x,
        y2: outer.y,
        class: "matrix-spoke",
      }));
    });

    if (state.baselineStatus === "ready" && state.baselineBlueprint) {
      const polygon = svgEl("polygon", {
        points: polygonPoints(entries, entry => baselineValue(entry)),
        class: "matrix-baseline-shape",
      });
      const baselineTitle = svgEl("title");
      baselineTitle.textContent = `Baseline ${state.baselineRevision}`;
      polygon.appendChild(baselineTitle);
      svg.appendChild(polygon);
    }

    svg.appendChild(svgEl("polygon", {
      points: polygonPoints(entries, entry => entry.value),
      class: "matrix-current-shape",
    }));

    const topIds = new Set(
      [...entries]
        .sort((a, b) => signatureScore(b) - signatureScore(a))
        .slice(0, LABEL_LIMIT)
        .map(entry => entry.traitId)
    );

    entries.forEach((entry, index) => {
      const point = pointFor(index, entries.length, entry.value);
      const circle = svgEl("circle", {
        cx: point.x,
        cy: point.y,
        r: entry.traitId === selected?.traitId ? 5.5 : topIds.has(entry.traitId) ? 4 : 2.6,
        class: [
          "matrix-node",
          topIds.has(entry.traitId) ? "signature" : "",
          entry.traitId === selected?.traitId ? "selected" : "",
        ].filter(Boolean).join(" "),
        tabindex: "0",
        role: "button",
        "aria-label": `${entry.label}, ${entry.value.toFixed(2)}`,
        "data-trait-id": entry.traitId,
      });
      const nodeTitle = svgEl("title");
      const base = baselineValue(entry);
      nodeTitle.textContent = base === null
        ? `${entry.label}: ${entry.value.toFixed(2)}`
        : `${entry.label}: ${entry.value.toFixed(2)} · baseline ${base.toFixed(2)}`;
      circle.appendChild(nodeTitle);
      const select = () => {
        state.selectedId = entry.traitId;
        scheduleRender();
      };
      circle.addEventListener("click", select);
      circle.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          select();
        }
      });
      svg.appendChild(circle);
    });

    const rawLabels = labelledEntries(entries, selected).map(item => ({ ...item, total: entries.length }));
    for (const item of relaxedLabels(rawLabels)) {
      const anchor = pointFor(item.index, entries.length, 1, RADIUS + 8);
      const lineEndX = item.side === "right" ? item.x - 8 : item.x + 8;
      svg.appendChild(svgEl("line", {
        x1: anchor.x,
        y1: anchor.y,
        x2: lineEndX,
        y2: item.y - 3,
        class: "matrix-label-line",
      }));

      const text = svgEl("text", {
        x: item.x,
        y: item.y,
        "text-anchor": item.side === "right" ? "end" : "start",
        class: `matrix-label${item.entry.traitId === selected?.traitId ? " selected" : ""}`,
        role: "button",
        tabindex: "0",
      });
      const name = svgEl("tspan", { x: item.x, dy: "0" });
      name.textContent = item.entry.label;
      const value = svgEl("tspan", {
        x: item.x,
        dy: "12",
        class: "matrix-value-label",
      });
      const base = baselineValue(item.entry);
      const delta = base === null ? "" : ` · Δ ${(item.entry.value - base >= 0 ? "+" : "")}${(item.entry.value - base).toFixed(2)}`;
      value.textContent = `${item.entry.value.toFixed(2)}${delta}`;
      text.append(name, value);
      const select = () => {
        state.selectedId = item.entry.traitId;
        scheduleRender();
      };
      text.addEventListener("click", select);
      text.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          select();
        }
      });
      svg.appendChild(text);
    }

    svg.appendChild(svgEl("circle", {
      cx: CENTER,
      cy: CENTER,
      r: 44,
      class: "matrix-core",
    }));
    const coreText = svgEl("text", { x: CENTER, y: CENTER - 3, class: "matrix-core-text" });
    coreText.textContent = state.ring === "inner" ? "INNER" : "OUTER";
    const coreSub = svgEl("text", { x: CENTER, y: CENTER + 14, class: "matrix-core-sub" });
    coreSub.textContent = "60 TRAITS";
    svg.append(coreText, coreSub);
  }

  function renderInspector(entry) {
    const name = $("matrixInspectorName");
    const meta = $("matrixInspectorMeta");
    const value = $("matrixInspectorValue");
    const range = $("matrixInspectorRange");
    const baseline = $("matrixBaselineReadout");
    if (!name || !meta || !value || !range || !baseline) return;

    if (!entry) {
      name.textContent = "—";
      meta.textContent = "Matrix-data er endnu ikke indlæst.";
      value.textContent = "0.50";
      range.value = "0.5";
      range.disabled = true;
      baseline.textContent = "Vælg en trait.";
      return;
    }

    range.disabled = false;
    name.textContent = entry.label;
    meta.textContent = `${entry.ring === "inner" ? "Inner" : "Outer"} Ring · ${entry.traitId}`;
    value.textContent = entry.value.toFixed(2);
    range.value = String(entry.value);

    const base = baselineValue(entry);
    if (state.baselineStatus === "loading") {
      baseline.textContent = `Henter baseline ${state.baselineRevision}…`;
    } else if (state.baselineStatus === "unavailable") {
      baseline.textContent = "Valgt revision har ingen verificeret Matrix v2 blueprint.";
    } else if (base === null) {
      baseline.textContent = "Vælg en Matrix v2-baseline for at se delta.";
    } else {
      const delta = entry.value - base;
      const sign = delta >= 0 ? "+" : "";
      baseline.replaceChildren();
      const line1 = document.createElement("div");
      line1.textContent = `Baseline ${state.baselineRevision}: ${base.toFixed(2)}`;
      const line2 = document.createElement("div");
      line2.className = delta >= 0 ? "matrix-delta-positive" : "matrix-delta-negative";
      line2.textContent = `Revision delta: ${sign}${delta.toFixed(2)}`;
      baseline.append(line1, line2);
    }
  }

  function renderStatus(entries) {
    const status = $("matrixStatus");
    if (!status) return;
    const changed = entries.filter(entry => Math.abs(entry.value - NEUTRAL) > EPSILON).length;
    const baselineText =
      state.baselineStatus === "ready" ? ` · baseline ${state.baselineRevision} overlay aktiv` :
      state.baselineStatus === "loading" ? " · baseline indlæses…" :
      state.baselineStatus === "unavailable" ? " · valgt baseline er ikke Matrix v2" : "";
    status.textContent = `${state.ring === "inner" ? "Inner" : "Outer"} Ring · ${changed}/60 traits ændret fra neutral${baselineText}. Kun de mest markante labels vises; alle 60 akser er tegnet.`;
  }

  function setSelectedValue(nextValue) {
    writeTraitValue(selectedEntry(), nextValue);
  }

  function toggleRawControls() {
    state.rawVisible = !state.rawVisible;
    document.body.classList.toggle("matrix-raw-hidden", !state.rawVisible);
    const button = $("matrixRawToggle");
    if (button) button.textContent = state.rawVisible ? "Skjul rå 120 sliders" : "Vis rå 120 sliders";
  }

  function jumpToRawSlider() {
    const entry = selectedEntry();
    if (!entry) return;
    if (!state.rawVisible) toggleRawControls();
    const details = entry.input.closest(".trait-ring");
    if (details) details.open = true;
    entry.input.scrollIntoView({ behavior: "smooth", block: "center" });
    entry.input.focus({ preventScroll: true });
  }

  function render() {
    if (!ensureUi()) return;
    void loadBaselineIfNeeded();
    const entries = traitEntries();
    if (!entries.length) return;
    const selected = ensureSelection(entries);
    renderSvg(entries, selected);
    renderInspector(selected);
    renderStatus(entries);
    syncSaveControls();
  }

  function scheduleRender() {
    if (state.scheduled) return;
    state.scheduled = true;
    requestAnimationFrame(() => {
      state.scheduled = false;
      render();
    });
  }

  const changeSummary = $("traitChangeSummary");
  if (!changeSummary) return;

  new MutationObserver(() => {
    scheduleRender();
    syncSaveControls();
  }).observe(changeSummary, {
    childList: true,
    characterData: true,
    subtree: true,
  });

  const saveUiObserver = new MutationObserver(syncSaveControls);
  for (const target of [$("previewButton"), $("saveButton"), $("status"), $("blueprintBadge")]) {
    if (target) saveUiObserver.observe(target, {
      attributes: true,
      attributeFilter: ["disabled", "class"],
      childList: true,
      characterData: true,
      subtree: true,
    });
  }

  const baselineSelect = $("baselineRevision");
  if (baselineSelect) {
    new MutationObserver(() => {
      syncCompareOptions();
      scheduleRender();
    }).observe(baselineSelect, {
      childList: true,
      subtree: true,
    });
  }

  $("personSelect")?.addEventListener("change", () => {
    syncCompareOptions();
    scheduleRender();
  });
  document.addEventListener("click", event => {
    const summaryButton = event.target.closest?.("#traitSignature button, #traitRevisionDelta button");
    if (summaryButton && !state.rawVisible) toggleRawControls();
  }, true);
  window.addEventListener("resize", scheduleRender);
  scheduleRender();
})();
