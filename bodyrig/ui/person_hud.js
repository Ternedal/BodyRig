(() => {
  const $ = (id) => document.getElementById(id);
  function setSignal(id, state) {
    const el = $(id);
    if (!el) return;
    el.classList.toggle("active", state === "bound");
    el.classList.toggle("unknown", state === "unknown");
  }

  function structuredHudState() {
    return window.BodyRigPersonState?.read() || null;
  }

  function attentionState() {
    const badge = $("operatorAttentionBadge");
    const active = Number(badge?.dataset?.activeCount);
    const unseen = Number(badge?.dataset?.unseenCount);
    return {
      active: Number.isInteger(active) && active >= 0 ? active : 0,
      unseen: Number.isInteger(unseen) && unseen >= 0 ? unseen : 0,
    };
  }

  function refresh() {
    const state = structuredHudState();
    const fidelity = window.BodyRigFidelityState?.read();
    const attention = attentionState();

    const complete = state?.complete ?? 0;
    const total = state?.total ?? 0;
    const pct = total > 0
      ? Math.max(0, Math.min(100, complete / total * 100))
      : 0;

    if ($("personHudName")) $("personHudName").textContent = state?.name || "—";
    if ($("personHudRevision")) {
      $("personHudRevision").textContent = state?.revision || "Ingen aktiv revision";
    }
    if ($("personHudPipeline")) {
      $("personHudPipeline").textContent = state ? `${complete}/${total}` : "—";
    }
    if ($("personHudMeterFill")) $("personHudMeterFill").style.width = `${pct}%`;

    setSignal("personHudBody", state?.body || "unknown");
    if ($("personHudBodyText")) {
      $("personHudBodyText").textContent = fidelity?.label
        ? `Krop · ${fidelity.label}`
        : "Krop";
    }
    if ($("personHudBody")) {
      $("personHudBody").title = fidelity?.label
        ? `Fidelity: ${fidelity.label}`
        : "Åbn Krop";
      $("personHudBody").classList.toggle(
        "has-new",
        window.BodyRigFidelityState?.requiresAttention(fidelity) === true
      );
    }
    setSignal("personHudVoice", state?.voice || "unknown");
    setSignal("personHudPersonality", state?.personality || "unknown");
    setSignal("personHudAttention", attention.active > 0 ? "bound" : "unbound");
    $("personHudAttention")?.classList.toggle("has-new", attention.unseen > 0);

    if ($("personHudAttentionText")) {
      $("personHudAttentionText").textContent = attention.active > 0
        ? `Drift · ${attention.active}${attention.unseen ? ` · NY ${attention.unseen}` : ""}`
        : "Drift";
    }
    if ($("personHudAttention")) {
      $("personHudAttention").title = attention.unseen > 0
        ? `${attention.unseen} nye operator-punkt${attention.unseen === 1 ? "" : "er"} siden sidste Live Activity-visning`
        : (attention.active > 0
            ? `${attention.active} aktive operator-punkter`
            : "Ingen aktive operator-punkter");
    }
  }

  for (const button of document.querySelectorAll(".person-hud-signal[data-target-tab]")) {
    button.addEventListener("click", () => {
      if (
        button.id === "personHudAttention"
        && attentionState().active > 0
        && $("personActivityToggle")
      ) {
        $("personActivityToggle").click();
        return;
      }
      const tab = button.dataset.targetTab;
      document.querySelector(`.tab[data-tab="${tab}"]`)?.click();
      if (button.id === "personHudBody") {
        const fidelity = window.BodyRigFidelityState?.read();
        if (window.BodyRigFidelityState?.requiresAttention(fidelity) === true) {
          window.BodyRigPersonNavigation?.focusFidelityCenter();
        }
      }
    });
  }

  const hud = $("personHud");
  if (hud) {
    new MutationObserver(refresh).observe(hud, {
      attributes: true,
      attributeFilter: [
        "data-state-version",
        "data-person-name",
        "data-person-revision",
        "data-pipeline-complete",
        "data-pipeline-total",
        "data-body-state",
        "data-voice-state",
        "data-personality-state",
      ],
    });
  }

  const bodyControl = $("bodyControlStrip");
  if (bodyControl) {
    new MutationObserver(refresh).observe(bodyControl, {
      attributes: true,
      attributeFilter: [
        "data-state-version",
        "data-fidelity-state",
        "data-fidelity-review-state",
        "data-fidelity-label",
      ],
    });
  }

  const attentionBadge = $("operatorAttentionBadge");
  if (attentionBadge) {
    new MutationObserver(refresh).observe(attentionBadge, {
      attributes: true,
      attributeFilter: ["data-active-count", "data-unseen-count"],
    });
  }

  window.addEventListener("bodyrig:attention-delta", refresh);
  window.addEventListener("bodyrig:attention-seen", refresh);
  refresh();
})();