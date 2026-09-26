(() => {
  const state = { mode: "guided" };

  function personId() {
    return (document.getElementById("personId")?.textContent || "").trim();
  }

  function sourceFor(mode) {
    const id = personId();
    const base = mode === "suite"
      ? "/ui/personality_audition_suite.html"
      : "/ui/personality_guided.html";
    return id ? `${base}?person_id=${encodeURIComponent(id)}` : base;
  }

  function setMode(mode, force = false) {
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

    const target = sourceFor(mode);
    if (force || frame.getAttribute("src") !== target) frame.setAttribute("src", target);
    status.textContent = mode === "guided"
      ? "Guided Personality · kandidat-authoring for valgt person."
      : "6-scenarie audition · supplementary review-evidence for valgt person.";
  }

  function popout() {
    window.open(sourceFor(state.mode), "_blank", "noopener,noreferrer");
  }

  document.getElementById("personalityWorkspaceGuided")?.addEventListener("click", () => setMode("guided"));
  document.getElementById("personalityWorkspaceSuite")?.addEventListener("click", () => setMode("suite"));
  document.getElementById("personalityWorkspacePopout")?.addEventListener("click", popout);

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