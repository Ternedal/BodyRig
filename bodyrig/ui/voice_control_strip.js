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

  function selectedVoiceLabel() {
    const select = $("voiceLibrarySelect");
    if (!select || !select.value) return "";
    return (select.selectedOptions?.[0]?.textContent || select.value || "").trim();
  }

  function candidateCount() {
    const host = $("voiceRevisions");
    if (!host) return 0;
    return [...host.children].filter((node) => (node.textContent || "").trim()).length;
  }

  function refresh() {
    const libraryStatus = text("voiceLibraryStatus");
    const selected = selectedVoiceLabel();
    const active = text("voiceActive").replace(/^Stemme\s+/, "");
    const count = candidateCount();

    setChip("voiceControlLibrary", libraryStatus || "VoiceRig status ukendt", /^\d+ validerede VoiceRig-stemmer\.$/i.test(libraryStatus));
    setChip("voiceControlSelected", selected || "Ingen valgt", Boolean(selected));
    setChip("voiceControlActive", active && active !== "—" ? active : "Ingen aktiv", Boolean(active && active !== "—"));

    const next = $("voiceControlNext");
    if (!next) return;
    if (!selected && count === 0) next.textContent = "Vælg en VoiceRig-stemme og gem den som kandidat.";
    else if (selected && count === 0) next.textContent = "Gem den valgte VoiceRig-stemme som kandidat.";
    else if (count > 0 && (!active || active === "—")) next.textContent = `${count} voice-kandidat(er) klar · fortsæt til Saml person.`;
    else next.textContent = `Aktiv stemme bundet · ${count} kandidat(er) tilgængelige.`;
  }

  $("voiceControlLibrary")?.addEventListener("click", () => {
    $("voiceLibrarySelect")?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("voiceControlSelected")?.addEventListener("click", () => {
    $("voiceLibrarySelect")?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("voiceControlActive")?.addEventListener("click", () => {
    document.querySelector('.tab[data-tab="assemble"]')?.click();
  });

  for (const id of ["voiceLibraryStatus", "voiceLibrarySelect", "voiceRevisions", "voiceActive"]) {
    const node = $(id);
    if (!node) continue;
    const options = id === "voiceLibrarySelect"
      ? { attributes: true, childList: true, subtree: true }
      : { childList: true, characterData: true, subtree: true };
    new MutationObserver(refresh).observe(node, options);
    if (id === "voiceLibrarySelect") node.addEventListener("change", refresh);
  }

  refresh();
})();