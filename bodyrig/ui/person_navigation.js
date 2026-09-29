(() => {
  function focusElement(target) {
    if (!target) return false;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
    target.scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" });
    target.classList.add("activity-focus");
    window.setTimeout(() => {
      if (target.isConnected) target.classList.remove("activity-focus");
    }, 1800);
    return true;
  }

  function focusFidelityCenter() {
    return focusElement(document.getElementById("highFidelityContinuationCard"));
  }

  window.BodyRigPersonNavigation = Object.freeze({
    focusElement,
    focusFidelityCenter,
  });
})();
