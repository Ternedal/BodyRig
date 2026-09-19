(() => {
  const LIMIT = 10;
  const NEUTRAL = 0.5;
  const EPSILON = 0.000001;
  const baselineState = {
    key: null,
    revision: null,
    status: "idle",
    blueprint: null,
  };

  function styleChipContainer(target) {
    target.setAttribute("aria-live", "polite");
    target.style.display = "flex";
    target.style.flexWrap = "wrap";
    target.style.gap = "7px";
    target.style.marginTop = "7px";
  }

  function ensureSummaryUi() {
    const changeSummary = document.getElementById("traitChangeSummary");
    if (!changeSummary) return null;

    let signatureTarget = document.getElementById("traitSignature");
    if (!signatureTarget) {
      const heading = document.createElement("div");
      heading.className = "fine-print";
      heading.style.marginTop = "10px";
      heading.style.fontWeight = "700";
      heading.textContent = "Signature traits · størst authored afvigelse fra neutral";

      signatureTarget = document.createElement("div");
      signatureTarget.id = "traitSignature";
      styleChipContainer(signatureTarget);

      const help = document.createElement("div");
      help.id = "traitSignatureHelp";
      help.className = "fine-print";
      help.style.marginTop = "7px";
      help.textContent = "Viser op til 10 traits ud fra de værdier, du selv har sat. Klik for at hoppe til den præcise slider.";

      changeSummary.insertAdjacentElement("afterend", heading);
      heading.insertAdjacentElement("afterend", signatureTarget);
      signatureTarget.insertAdjacentElement("afterend", help);
    }

    let deltaTarget = document.getElementById("traitRevisionDelta");
    if (!deltaTarget) {
      const signatureHelp = document.getElementById("traitSignatureHelp") || signatureTarget;
      const heading = document.createElement("div");
      heading.className = "fine-print";
      heading.style.marginTop = "12px";
      heading.style.fontWeight = "700";
      heading.textContent = "Revision delta · mod valgt Matrix v2 baseline";

      deltaTarget = document.createElement("div");
      deltaTarget.id = "traitRevisionDelta";
      styleChipContainer(deltaTarget);

      const help = document.createElement("div");
      help.className = "fine-print";
      help.style.marginTop = "7px";
      help.textContent = "Read-only sammenligning med det verificerede blueprint for den valgte personality-revision. Delta gemmes ikke.";

      signatureHelp.insertAdjacentElement("afterend", heading);
      heading.insertAdjacentElement("afterend", deltaTarget);
      deltaTarget.insertAdjacentElement("afterend", help);
    }

    return { signatureTarget, deltaTarget };
  }

  function allTraitEntries() {
    const entries = [];
    for (const [containerId, ring, ringLabel] of [
      ["innerTraits", "inner", "Inner"],
      ["outerTraits", "outer", "Outer"],
    ]) {
      const container = document.getElementById(containerId);
      if (!container) continue;
      for (const row of container.querySelectorAll(".trait-slider-row")) {
        const input = row.querySelector('input[type="range"]');
        const label = row.querySelector("label");
        if (!input || !label) continue;
        const value = Number(input.value);
        if (!Number.isFinite(value)) continue;
        const prefix = `trait-${ring}-`;
        if (!input.id.startsWith(prefix)) continue;
        entries.push({
          input,
          traitId: input.id.slice(prefix.length),
          label: label.textContent.trim(),
          ring,
          ringLabel,
          value,
        });
      }
    }
    return entries;
  }

  function sortByMagnitude(entries, field) {
    entries.sort(
      (left, right) =>
        right[field] - left[field] ||
        left.label.localeCompare(right.label, "da") ||
        left.ring.localeCompare(right.ring)
    );
    return entries;
  }

  function signatureEntries(entries) {
    return sortByMagnitude(
      entries
        .map(entry => ({ ...entry, delta: Math.abs(entry.value - NEUTRAL) }))
        .filter(entry => entry.delta > EPSILON),
      "delta"
    );
  }

  function baselineSelection() {
    const personId = document.getElementById("personSelect")?.value || "";
    const compareSelect = document.getElementById("matrixCompareRevision");
    const revision = compareSelect
      ? compareSelect.value
      : (document.getElementById("baselineRevision")?.value || "");
    if (!personId || !revision) return null;
    return {
      personId,
      revision,
      key: `${personId}|${revision}`,
    };
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
      if (baselineState.key !== null || baselineState.status !== "idle") {
        baselineState.key = null;
        baselineState.revision = null;
        baselineState.status = "idle";
        baselineState.blueprint = null;
        scheduleRender();
      }
      return;
    }
    if (selection.key === baselineState.key) return;

    baselineState.key = selection.key;
    baselineState.revision = selection.revision;
    baselineState.status = "loading";
    baselineState.blueprint = null;
    scheduleRender();

    try {
      const response = await fetch(
        `/api/v1/people/${encodeURIComponent(selection.personId)}/personality/guided/revisions/${encodeURIComponent(selection.revision)}`
      );
      if (baselineState.key !== selection.key) return;
      if (!response.ok) {
        baselineState.status = "unavailable";
        scheduleRender();
        return;
      }
      const source = await response.json();
      if (baselineState.key !== selection.key) return;
      if (!validMatrixBlueprint(source?.blueprint)) {
        baselineState.status = "unavailable";
        scheduleRender();
        return;
      }
      baselineState.status = "ready";
      baselineState.blueprint = source.blueprint;
      scheduleRender();
    } catch (_error) {
      if (baselineState.key !== selection.key) return;
      baselineState.status = "unavailable";
      baselineState.blueprint = null;
      scheduleRender();
    }
  }

  function revisionDeltaEntries(entries) {
    if (baselineState.status !== "ready" || !baselineState.blueprint) return [];
    const result = [];
    for (const entry of entries) {
      const ringValues = baselineState.blueprint[`${entry.ring}_ring`];
      const baselineValue = Number(ringValues?.[entry.traitId]);
      if (!Number.isFinite(baselineValue)) continue;
      const signedDelta = entry.value - baselineValue;
      const delta = Math.abs(signedDelta);
      if (delta <= EPSILON) continue;
      result.push({
        ...entry,
        baselineValue,
        signedDelta,
        delta,
      });
    }
    return sortByMagnitude(result, "delta");
  }

  function clearTraitFilters() {
    const search = document.getElementById("traitSearch");
    if (search && search.value) {
      search.value = "";
      search.dispatchEvent(new Event("input", { bubbles: true }));
    }
    const changedOnly = document.getElementById("changedTraitsOnly");
    if (changedOnly && changedOnly.checked) {
      changedOnly.checked = false;
      changedOnly.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  function focusTrait(entry) {
    clearTraitFilters();
    const details = entry.input.closest(".trait-ring");
    if (details) details.open = true;
    entry.input.scrollIntoView({ behavior: "smooth", block: "center" });
    entry.input.focus({ preventScroll: true });
  }

  function emptyMessage(target, message) {
    target.replaceChildren();
    const empty = document.createElement("span");
    empty.className = "fine-print";
    empty.textContent = message;
    target.appendChild(empty);
  }

  function traitButton(entry, metaText, title) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.style.padding = "6px 9px";
    button.style.borderRadius = "999px";
    button.title = title;

    const label = document.createElement("strong");
    label.textContent = entry.label;

    const meta = document.createElement("span");
    meta.className = "muted-text";
    meta.style.marginLeft = "6px";
    meta.style.fontVariantNumeric = "tabular-nums";
    meta.textContent = metaText;

    button.append(label, meta);
    button.addEventListener("click", () => focusTrait(entry));
    return button;
  }

  function renderSignature(target, entries) {
    target.replaceChildren();
    const signature = signatureEntries(entries);
    if (!signature.length) {
      emptyMessage(target, "Ingen traits afviger fra neutral endnu.");
      return;
    }
    for (const entry of signature.slice(0, LIMIT)) {
      target.appendChild(
        traitButton(
          entry,
          `${entry.ringLabel} · ${entry.value > NEUTRAL ? "↑" : "↓"} ${entry.value.toFixed(2)}`,
          `Hop til ${entry.label} i ${entry.ringLabel} Ring`
        )
      );
    }
  }

  function renderRevisionDelta(target, entries) {
    if (!baselineSelection()) {
      emptyMessage(target, "Vælg en personality-revision som baseline for at se revisions-delta.");
      return;
    }
    if (baselineState.status === "loading") {
      emptyMessage(target, `Henter verificeret Matrix v2 baseline ${baselineState.revision}…`);
      return;
    }
    if (baselineState.status !== "ready" || !baselineState.blueprint) {
      emptyMessage(target, "Valgt baseline har ingen verificeret Matrix v2 blueprint.");
      return;
    }

    target.replaceChildren();
    const deltaEntries = revisionDeltaEntries(entries);
    if (!deltaEntries.length) {
      emptyMessage(target, `Ingen trait-værdier ændret fra ${baselineState.revision}.`);
      return;
    }

    for (const entry of deltaEntries.slice(0, LIMIT)) {
      const sign = entry.signedDelta > 0 ? "+" : "";
      target.appendChild(
        traitButton(
          entry,
          `${entry.ringLabel} · Δ ${sign}${entry.signedDelta.toFixed(2)} · nu ${entry.value.toFixed(2)}`,
          `Hop til ${entry.label}; baseline ${entry.baselineValue.toFixed(2)}, nu ${entry.value.toFixed(2)}`
        )
      );
    }
  }

  function render() {
    const targets = ensureSummaryUi();
    if (!targets) return;
    const entries = allTraitEntries();
    renderSignature(targets.signatureTarget, entries);
    void loadBaselineIfNeeded();
    renderRevisionDelta(targets.deltaTarget, entries);
  }

  let scheduled = false;
  function scheduleRender() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      render();
    });
  }

  const changeSummary = document.getElementById("traitChangeSummary");
  if (!changeSummary) return;

  new MutationObserver(scheduleRender).observe(changeSummary, {
    childList: true,
    characterData: true,
    subtree: true,
  });

  const baselineSelect = document.getElementById("baselineRevision");
  if (baselineSelect) {
    baselineSelect.addEventListener("change", scheduleRender);
    new MutationObserver(scheduleRender).observe(baselineSelect, {
      childList: true,
      subtree: true,
    });
  }
  document.getElementById("personSelect")?.addEventListener("change", scheduleRender);
  document.addEventListener("bodyrig:matrix-compare-change", scheduleRender);

  scheduleRender();
})();
