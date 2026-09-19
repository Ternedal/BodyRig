(() => {
  const LIMIT = 10;
  const NEUTRAL = 0.5;
  const EPSILON = 0.000001;

  function ensureSummaryUi() {
    const changeSummary = document.getElementById("traitChangeSummary");
    if (!changeSummary) return null;

    let target = document.getElementById("traitSignature");
    if (target) return target;

    const heading = document.createElement("div");
    heading.className = "fine-print";
    heading.style.marginTop = "10px";
    heading.style.fontWeight = "700";
    heading.textContent = "Signature traits · størst authored afvigelse fra neutral";

    target = document.createElement("div");
    target.id = "traitSignature";
    target.setAttribute("aria-live", "polite");
    target.style.display = "flex";
    target.style.flexWrap = "wrap";
    target.style.gap = "7px";
    target.style.marginTop = "7px";

    const help = document.createElement("div");
    help.className = "fine-print";
    help.style.marginTop = "7px";
    help.textContent = "Viser op til 10 traits ud fra de værdier, du selv har sat. Klik for at hoppe til den præcise slider.";

    changeSummary.insertAdjacentElement("afterend", heading);
    heading.insertAdjacentElement("afterend", target);
    target.insertAdjacentElement("afterend", help);
    return target;
  }

  function traitEntries() {
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
        const delta = Math.abs(value - NEUTRAL);
        if (delta <= EPSILON) continue;
        entries.push({
          input,
          label: label.textContent.trim(),
          ring,
          ringLabel,
          value,
          delta,
        });
      }
    }
    entries.sort(
      (left, right) =>
        right.delta - left.delta ||
        left.label.localeCompare(right.label, "da") ||
        left.ring.localeCompare(right.ring)
    );
    return entries;
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

  function render() {
    const target = ensureSummaryUi();
    if (!target) return;
    target.replaceChildren();

    const entries = traitEntries();
    if (!entries.length) {
      const empty = document.createElement("span");
      empty.className = "fine-print";
      empty.textContent = "Ingen traits afviger fra neutral endnu.";
      target.appendChild(empty);
      return;
    }

    for (const entry of entries.slice(0, LIMIT)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.style.padding = "6px 9px";
      button.style.borderRadius = "999px";
      button.title = `Hop til ${entry.label} i ${entry.ringLabel} Ring`;

      const label = document.createElement("strong");
      label.textContent = entry.label;

      const meta = document.createElement("span");
      meta.className = "muted-text";
      meta.style.marginLeft = "6px";
      meta.style.fontVariantNumeric = "tabular-nums";
      meta.textContent = `${entry.ringLabel} · ${entry.value > NEUTRAL ? "↑" : "↓"} ${entry.value.toFixed(2)}`;

      button.append(label, meta);
      button.addEventListener("click", () => focusTrait(entry));
      target.appendChild(button);
    }
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

  scheduleRender();
})();
