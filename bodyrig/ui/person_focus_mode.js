(() => {
  const STORAGE_KEY = "bodyrig.personStudio.focusMode";
  const toggle = document.getElementById("personFocusToggle");
  const label = document.getElementById("personFocusToggleText");

  function readStored() {
    try {
      return window.localStorage.getItem(STORAGE_KEY) === "1";
    } catch {
      return false;
    }
  }

  function persist(enabled) {
    try {
      window.localStorage.setItem(STORAGE_KEY, enabled ? "1" : "0");
    } catch {
      // Presentation preference only. Failure to persist must not affect Person Studio authority.
    }
  }

  function apply(enabled, save = true) {
    document.body.classList.toggle("person-focus-mode", enabled);
    toggle?.classList.toggle("active", enabled);
    toggle?.setAttribute("aria-pressed", String(enabled));
    if (label) label.textContent = enabled ? "Exit focus" : "Focus";
    if (save) persist(enabled);
  }

  toggle?.addEventListener("click", () => {
    apply(!document.body.classList.contains("person-focus-mode"));
  });

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const typing = target instanceof HTMLInputElement
      || target instanceof HTMLTextAreaElement
      || target instanceof HTMLSelectElement
      || target?.isContentEditable;
    if (typing) return;
    if (event.key.toLowerCase() === "f" && event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      toggle?.click();
    }
  });

  apply(readStored(), false);
})();