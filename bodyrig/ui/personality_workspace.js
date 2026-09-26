(() => {
  const state = { mode: "guided" };

  function personId() {
    return (document.getElementById("personId")?.textContent || "").trim();
  }

  function sourceFor(mode, extra = {}) {
    const id = personId();
    const base = mode === "suite"
      ? "/ui/personality_audition_suite.html"
      : "/ui/personality_guided.html";
    const params = new URLSearchParams();
    if (id) params.set("person_id", id);
    params.set("embedded", "1");
    for (const [key, value] of Object.entries(extra || {})) {
      if (value) params.set(key, value);
    }
    return `${base}?${params.toString()}`;
  }

  function publishLabState(mode, label) {
    const root = document.getElementById("personalityControlStrip");
    if (!root) return;
    const id = personId();
    root.dataset.stateVersion = "1";
    root.dataset.labPersonId = id;
    root.dataset.labMode = mode;
    root.dataset.labState = id ? "ready" : "blocked";
    root.dataset.labLabel = id ? label : "Vælg en person";
  }

  function setMode(mode, force = false, extra = {}) {
    if (!["guided", "suite"].includes(mode)) return;
    state.mode = mode;
    const guided = document.getElementById("personalityWorkspaceGuided");
    const suite = document.getElementById("personalityWorkspaceSuite");
    const frame = document.getElementById("personalityWorkspaceFrame");
    const status = document.getElementById("personalityWorkspaceStatus");
    if (!guided || !suite || !frame || !status) return;

    guided.classList.toggle("active", mode === "guided");
    suite.classList.toggle("active", mode === "suite");
    guided.setAttribute("aria-selected", String(mode === "guided"));
    suite.setAttribute("aria-selected", String(mode === "suite"));

    const target = sourceFor(mode, extra);
    if (force || frame.getAttribute("src") !== target) frame.setAttribute("src", target);
    const label = mode === "guided"
      ? "Guided Personality · kandidat-authoring for valgt person."
      : "6-scenarie audition · supplementary review-evidence for valgt person.";
    status.textContent = label;
    publishLabState(mode, label);
  }

  function popout() {
    const target = sourceFor(state.mode).replace(/([?&])embedded=1(&|$)/, (match, lead, tail) => tail ? lead : "");
    window.open(target, "_blank", "noopener,noreferrer");
  }

  function styleEmbeddedFrame() {
    const frame = document.getElementById("personalityWorkspaceFrame");
    if (!frame) return;
    try {
      const doc = frame.contentDocument;
      if (!doc?.head) return;
      if (doc.getElementById("bodyrigEmbeddedWorkspaceStyle")) return;
      const style = doc.createElement("style");
      style.id = "bodyrigEmbeddedWorkspaceStyle";
      style.textContent = `
        .guided-head,.suite-head{display:none!important}
        .guided-shell,.suite-shell{max-width:none!important;padding:16px!important}
        body{background:transparent!important}
      `;
      doc.head.appendChild(style);
    } catch {
      // Same-origin is expected; fail closed to the standalone rendering if unavailable.
    }
  }

  function openGuidedRevision(url) {
    const parsed = new URL(url, window.location.origin);
    const edit = parsed.searchParams.get("edit_revision") || "";
    const baseline = parsed.searchParams.get("baseline_revision") || "";
    setMode("guided", true, {
      edit_revision: edit,
      baseline_revision: baseline,
    });
    document.querySelector('.tab[data-tab="personality"]')?.click();
    document.querySelector(".personality-workspace-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  document.getElementById("personalityWorkspaceGuided")?.addEventListener("click", () => setMode("guided"));
  document.getElementById("personalityWorkspaceSuite")?.addEventListener("click", () => setMode("suite"));
  document.getElementById("personalityWorkspacePopout")?.addEventListener("click", popout);
  document.getElementById("personalityWorkspaceFrame")?.addEventListener("load", styleEmbeddedFrame);

  document.addEventListener("click", (event) => {
    const link = event.target.closest?.(".personality-matrix-link");
    if (!link) return;
    const href = link.getAttribute("href") || "";
    if (!href.startsWith("/ui/personality_guided.html")) return;
    event.preventDefault();
    openGuidedRevision(href);
  });

  const personNode = document.getElementById("personId");
  if (personNode) {
    new MutationObserver(() => setMode(state.mode, true))
      .observe(personNode, { childList: true, characterData: true, subtree: true });
  }

  document.querySelector('.tab[data-tab="personality"]')?.addEventListener("click", () => {
    setTimeout(() => setMode(state.mode), 0);
  });

  setMode("guided", true);
})();