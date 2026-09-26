(() => {
  const $ = (id) => document.getElementById(id);
  const ALLOWED = {
    pipeline: new Set(["complete", "incomplete", "unknown"]),
    revision: new Set(["bound", "unbound", "invalid", "unknown"]),
    twin: new Set(["ready", "not-ready", "unknown"]),
  };

  function setChip(id, state, active) {
    const chip = $(id);
    if (!chip) return;
    const node = chip.querySelector(".chip-state");
    if (node) node.textContent = state || "Ukendt";
    chip.classList.toggle("active", Boolean(active));
  }

  function structuredState() {
    const root = $("overviewControlStrip");
    if (!root || root.dataset.stateVersion !== "1") return null;

    const pipeline = String(root.dataset.pipelineState || "").trim();
    const revision = String(root.dataset.revisionState || "").trim();
    const twin = String(root.dataset.twinState || "").trim();
    const pipelineLabel = String(root.dataset.pipelineLabel || "").trim();
    const revisionLabel = String(root.dataset.revisionLabel || "").trim();
    const twinLabel = String(root.dataset.twinLabel || "").trim();
    const nextLabel = String(root.dataset.nextLabel || "").trim();

    if (
      !ALLOWED.pipeline.has(pipeline)
      || !ALLOWED.revision.has(revision)
      || !ALLOWED.twin.has(twin)
      || pipelineLabel.length > 240
      || revisionLabel.length > 240
      || twinLabel.length > 240
      || nextLabel.length > 1000
    ) {
      return null;
    }

    return { pipeline, revision, twin, pipelineLabel, revisionLabel, twinLabel, nextLabel };
  }

  function refresh() {
    const state = structuredState();
    if (!state) {
      setChip("overviewControlPipeline", "Ukendt", false);
      setChip("overviewControlRevision", "Ukendt", false);
      setChip("overviewControlTwin", "Ukendt", false);
      if ($("overviewControlNext")) {
        $("overviewControlNext").textContent = "Afventer struktureret Overview-status…";
      }
      return;
    }

    setChip(
      "overviewControlPipeline",
      state.pipelineLabel || "Ukendt",
      state.pipeline === "complete"
    );
    setChip(
      "overviewControlRevision",
      state.revisionLabel || "Ingen aktiv",
      state.revision === "bound"
    );
    setChip(
      "overviewControlTwin",
      state.twinLabel || "Ukendt",
      state.twin === "ready"
    );

    const node = $("overviewControlNext");
    if (node) node.textContent = state.nextLabel || "Ingen prioriteret handling.";
  }

  $("overviewControlPipeline")?.addEventListener("click", () =>
    $("overviewCockpitStages")?.scrollIntoView({ behavior: "smooth", block: "start" })
  );
  $("overviewControlRevision")?.addEventListener("click", () =>
    document.querySelector('.tab[data-tab="history"]')?.click()
  );
  $("overviewControlTwin")?.addEventListener("click", () =>
    document.querySelector('.tab[data-tab="operations"]')?.click()
  );

  const root = $("overviewControlStrip");
  if (root) {
    new MutationObserver(refresh).observe(root, {
      attributes: true,
      attributeFilter: [
        "data-state-version",
        "data-pipeline-state",
        "data-pipeline-label",
        "data-revision-state",
        "data-revision-label",
        "data-twin-state",
        "data-twin-label",
        "data-next-label",
      ],
    });
  }

  refresh();
})();