(() => {
  const $ = (id) => document.getElementById(id);

  function text(id) {
    return ($(id)?.textContent || "").replace(/\s+/g, " ").trim();
  }

  function setChip(id, state, active) {
    const chip = $(id);
    if (!chip) return;
    const stateNode = chip.querySelector(".chip-state");
    if (stateNode) stateNode.textContent = state || "—";
    chip.classList.toggle("active", Boolean(active));
  }

  function candidateCount() {
    const host = $("personalityRevisions");
    if (!host) return 0;
    return [...host.children].filter((node) => (node.textContent || "").trim()).length;
  }

  function refresh() {
    const count = candidateCount();
    const lab = text("personalityWorkspaceStatus");
    const active = text("personalityActive").replace(/^Personlighed\s+/, "");

    setChip("personalityControlDraft", count ? `${count} kandidat(er)` : "Ingen kandidater", count > 0);
    setChip("personalityControlLab", lab || "Guided + Audition", Boolean(lab && !/fejl|ikke klar/i.test(lab)));
    setChip("personalityControlActive", active && active !== "—" ? active : "Ingen aktiv", Boolean(active && active !== "—"));

    const next = $("personalityControlNext");
    if (!next) return;
    if (count === 0) next.textContent = "Opret en personality-kandidat eller brug Guided Personality.";
    else if (!active || active === "—") next.textContent = `${count} kandidat(er) klar · kør audition og fortsæt til Saml person.`;
    else next.textContent = `Aktiv personality bundet · ${count} kandidat(er) tilgængelige.`;
  }

  $("personalityControlDraft")?.addEventListener("click", () => {
    $("personalityRevisions")?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("personalityControlLab")?.addEventListener("click", () => {
    document.querySelector(".personality-workspace-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("personalityControlActive")?.addEventListener("click", () => {
    document.querySelector('.tab[data-tab="assemble"]')?.click();
  });

  for (const id of ["personalityRevisions", "personalityWorkspaceStatus", "personalityActive"]) {
    const node = $(id);
    if (!node) continue;
    new MutationObserver(refresh).observe(node, { childList: true, characterData: true, subtree: true });
  }

  refresh();
})();