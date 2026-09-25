(() => {
  let timer = null;
  let requestSerial = 0;
  let inputValues = {};

  const STAGES = [
    ["p0_ready", "P0 · source/identity"],
    ["static_teacher_built", "P1 · static teacher"],
    ["p2_animated_teacher_status", "P2 · animation"],
    ["p3_runtime_review_status", "P3 · device/runtime"],
  ];

  function currentPersonId() {
    return (document.getElementById("personId")?.textContent || "").trim();
  }

  function ensureCard() {
    let card = document.getElementById("photorealControlPlaneCard");
    if (card) return card;
    const tab = document.getElementById("tab-body");
    if (!tab) return null;
    card = document.createElement("article");
    card.id = "photorealControlPlaneCard";
    card.className = "card space-top photoreal-control-plane";
    card.innerHTML = `
      <div class="card-row">
        <div>
          <div class="card-label">Photoreal V2 · Control Plane</div>
          <div id="photorealControlSummary" class="muted-text">Henter pipeline-status…</div>
        </div>
        <div class="action-row">
          <button id="photorealControlRefresh" class="secondary" type="button">Opdatér</button>
          <button id="photorealControlAdvance" class="primary" type="button" disabled>Kør næste sikre trin</button>
          <span id="photorealControlBadge" class="badge muted">Ukendt</span>
        </div>
      </div>
      <div id="photorealControlStages" class="photoreal-control-stages"></div>
      <div class="photoreal-control-grid space-top">
        <section class="photoreal-control-panel">
          <div class="card-label">Næste gate</div>
          <div id="photorealControlNextGate" class="photoreal-control-value">—</div>
          <div id="photorealControlMessage" class="fine-print"></div>
          <div id="photorealControlInputs" class="photoreal-control-inputs"></div>
        </section>
        <section class="photoreal-control-panel">
          <div class="card-label">ExAvatar live</div>
          <div id="photorealExavatarPhase" class="photoreal-control-value">—</div>
          <div id="photorealExavatarProgress" class="fine-print"></div>
          <div id="photorealExavatarActivity" class="fine-print"></div>
        </section>
      </div>
      <details class="space-top">
        <summary>Seneste ExAvatar-log</summary>
        <pre id="photorealExavatarLog" class="proposal photoreal-control-log">Ingen log endnu.</pre>
      </details>
      <pre id="photorealControlCommand" class="proposal photoreal-control-command hidden"></pre>
      <p class="fine-print">
        UI'et kan kun starte den next_command, som BodyRigs canonicale statusmotor netop har genberegnet.
        Browseren kan ikke sende en vilkårlig shell-kommando, og en aktiv ExAvatar-proces blokerer parallel launch.
        Human review og production authority forbliver eksplicitte gates.
      </p>
    `;
    const calibration = document.getElementById("photorealCalibrationCard");
    if (calibration) calibration.insertAdjacentElement("afterend", card);
    else tab.prepend(card);
    document.getElementById("photorealControlRefresh")?.addEventListener("click", () => void refresh(true));
    document.getElementById("photorealControlAdvance")?.addEventListener("click", () => void advance());
    return card;
  }

  function n(id) {
    ensureCard();
    return document.getElementById(id);
  }

  function apiJson(url, options = {}) {
    return fetch(url, {
      ...options,
      headers: { Accept: "application/json", "Content-Type": "application/json", ...(options.headers || {}) },
      cache: "no-store",
    }).then(async (response) => {
      let payload = null;
      try { payload = await response.json(); } catch { payload = null; }
      if (!response.ok) throw new Error(payload?.detail || `HTTP ${response.status}`);
      return payload;
    });
  }

  function badgeText(state) {
    return ({
      complete: "Komplet",
      required: "Næste trin",
      "human-review-required": "Human review",
      "operator-input-required": "Input kræves",
      blocked: "Blokeret",
      "no-run": "Ingen run",
    })[state] || state || "Ukendt";
  }

  function stageState(pipeline, key) {
    if (!pipeline) return "unknown";
    if (key === "p0_ready") return pipeline.p0_ready === true ? "pass" : "pending";
    if (key === "static_teacher_built") return pipeline.static_teacher_built === true ? "pass" : "pending";
    if (key === "p2_animated_teacher_status") return pipeline.p2_animated_teacher_status === "pass" ? "pass" : "pending";
    if (key === "p3_runtime_review_status") return pipeline.p3_runtime_review_status === "pass" ? "pass" : "pending";
    return "pending";
  }

  function renderStages(pipeline) {
    const host = n("photorealControlStages");
    host.replaceChildren();
    for (const [key, label] of STAGES) {
      const state = stageState(pipeline, key);
      const item = document.createElement("div");
      item.className = `photoreal-control-stage ${state}`;
      const strong = document.createElement("strong");
      strong.textContent = label;
      const span = document.createElement("span");
      span.textContent = state === "pass" ? "PASS" : "Afventer";
      item.append(strong, span);
      host.appendChild(item);
    }
  }

  function inputControl(name) {
    const wrap = document.createElement("label");
    wrap.className = "photoreal-control-input";
    const caption = document.createElement("span");
    caption.textContent = name.replaceAll("_", " ");
    wrap.appendChild(caption);

    let control;
    if (name === "smplx_gender") {
      control = document.createElement("select");
      for (const value of ["", "female", "male", "neutral"]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value || "Vælg…";
        control.appendChild(option);
      }
    } else if (name === "camera_mode") {
      control = document.createElement("select");
      for (const value of ["", "virtual", "colmap"]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value || "Vælg…";
        control.appendChild(option);
      }
    } else if (name === "setup_public_code" || name === "setup_runtime") {
      control = document.createElement("input");
      control.type = "checkbox";
      control.checked = inputValues[name] === true;
    } else {
      control = document.createElement("input");
      control.type = "text";
      control.placeholder = "Operator-input";
    }
    if (control.type !== "checkbox") control.value = inputValues[name] || "";
    control.addEventListener("change", () => {
      inputValues[name] = control.type === "checkbox" ? control.checked : control.value;
    });
    wrap.appendChild(control);
    return wrap;
  }

  function renderInputs(missing) {
    const host = n("photorealControlInputs");
    host.replaceChildren();
    const values = Array.isArray(missing) ? missing : [];
    if (!values.length) return;
    const intro = document.createElement("div");
    intro.className = "fine-print";
    intro.textContent = "BodyRig gætter ikke disse værdier. Udfyld dem før næste launch:";
    host.appendChild(intro);
    for (const name of values) host.appendChild(inputControl(name));
  }

  function renderExavatar(exavatar) {
    const value = exavatar && typeof exavatar === "object" ? exavatar : {};
    n("photorealExavatarPhase").textContent = value.phase || "ukendt";
    const preprocessDone = Number(value.preprocess_completed_count || 0);
    const preprocessTotal = Number(value.preprocess_total_count || 9);
    const epoch = value.highest_snapshot_epoch;
    const target = Number(value.training_target_epoch ?? 4);
    const neutral = Number(value.neutral_render_count || 0);
    n("photorealExavatarProgress").textContent =
      `Preprocess ${preprocessDone}/${preprocessTotal} · checkpoints ${epoch == null ? "0" : Number(epoch) + 1}/${target + 1} · neutral renders ${neutral}/50.`;

    const active = Array.isArray(value.active_processes) ? value.active_processes : [];
    const latest = value.latest_log || {};
    const activity = value.activity && typeof value.activity === "object" ? value.activity : {};
    const age = (seconds) => {
      const number = Number(seconds);
      if (!Number.isFinite(number) || number < 0) return "ukendt";
      if (number < 90) return `${Math.round(number)} s`;
      if (number < 5400) return `${Math.round(number / 60)} min`;
      return `${(number / 3600).toFixed(1)} t`;
    };
    const liveness = [
      activity.stalled_suspected === true ? "MULIG STALL" : (activity.state || "ukendt liveness"),
      `log-alder ${age(activity.latest_log_age_seconds)}`,
      `procesalder ${age(activity.oldest_active_process_age_seconds)}`,
      activity.reason || "",
    ].filter(Boolean).join(" · ");
    n("photorealExavatarActivity").textContent = active.length
      ? `Aktive WSL-processer: ${active.length}. Seneste log: ${latest.name || "—"} · ${latest.modified_utc || "ukendt tid"}. ${liveness}.`
      : `Ingen ExAvatar-proces fundet af read-only process probe. Seneste log: ${latest.name || "—"} · ${latest.modified_utc || "ukendt tid"}. ${liveness}.`;
    n("photorealExavatarLog").textContent = latest.tail || "Ingen log endnu.";
  }

  function render(value) {
    const pipeline = value.pipeline || null;
    renderStages(pipeline);
    renderExavatar(value.exavatar);
    const state = value.state || "unknown";
    const badge = n("photorealControlBadge");
    badge.textContent = badgeText(state);
    badge.classList.toggle("muted", state !== "complete");

    if (!pipeline) {
      n("photorealControlSummary").textContent = "Ingen Photoreal P0-run fundet for denne person.";
      n("photorealControlNextGate").textContent = "—";
      n("photorealControlMessage").textContent = "";
      renderInputs([]);
    } else {
      n("photorealControlSummary").textContent =
        `${value.performer?.name || "Performer"} · P0 ${value.p0_root || "?"}`;
      n("photorealControlNextGate").textContent = pipeline.next_gate || (state === "complete" ? "Komplet" : "—");
      n("photorealControlMessage").textContent = pipeline.message || "";
      renderInputs(pipeline.missing_operator_inputs);
    }

    const command = typeof pipeline?.next_command === "string" ? pipeline.next_command.trim() : "";
    const commandNode = n("photorealControlCommand");
    if (command) {
      commandNode.textContent = command;
      commandNode.classList.remove("hidden");
    } else {
      commandNode.textContent = "";
      commandNode.classList.add("hidden");
    }

    const button = n("photorealControlAdvance");
    button.disabled = value.advance_allowed !== true && state !== "operator-input-required";
    button.textContent = state === "operator-input-required" ? "Brug input og beregn næste trin" : "Kør næste sikre trin";

    const busy = value.exavatar?.busy === true;
    const stalled = value.exavatar?.activity?.stalled_suspected === true;
    if (busy) {
      button.disabled = true;
      button.textContent = stalled ? "ExAvatar kører · mulig stall" : "ExAvatar kører";
    }

    schedule(busy ? 5000 : 15000);
  }

  function reset(message) {
    n("photorealControlSummary").textContent = message;
    n("photorealControlBadge").textContent = "Ukendt";
    n("photorealControlBadge").classList.add("muted");
    n("photorealControlNextGate").textContent = "—";
    n("photorealControlMessage").textContent = "";
    renderStages(null);
    renderInputs([]);
    renderExavatar({});
    n("photorealControlAdvance").disabled = true;
    schedule(15000);
  }

  function schedule(delay) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => void refresh(true), delay);
  }

  async function refresh(force = false) {
    ensureCard();
    const personId = currentPersonId();
    if (!personId) return reset("Ingen person valgt.");
    const serial = ++requestSerial;
    if (force) n("photorealControlSummary").textContent = "Revaliderer pipeline + ExAvatar live-status…";
    try {
      const value = await apiJson(
        `/api/v1/people/${encodeURIComponent(personId)}/body/photoreal-control-plane`
      );
      if (serial !== requestSerial || currentPersonId() !== personId) return;
      render(value);
    } catch (error) {
      if (serial !== requestSerial) return;
      reset(`Fail-closed: ${error.message}`);
    }
  }

  async function advance() {
    const personId = currentPersonId();
    if (!personId) return;
    const button = n("photorealControlAdvance");
    button.disabled = true;
    button.textContent = "Starter canonicalt trin…";
    try {
      const value = await apiJson(
        `/api/v1/people/${encodeURIComponent(personId)}/body/photoreal-control-plane/action`,
        { method: "POST", body: JSON.stringify({ action: "advance", inputs: inputValues }) }
      );
      if (value.launched === true) {
        n("photorealControlMessage").textContent =
          `Startet ${value.launch?.gate || "næste gate"} · PID ${value.launch?.pid || "?"}. UI følger artifacts og ExAvatar-processer.`;
      } else if (value.status) {
        render(value.status);
        n("photorealControlMessage").textContent = value.reason || value.status.pipeline?.message || "Input mangler.";
      }
      schedule(2500);
    } catch (error) {
      n("photorealControlMessage").textContent = `Launch afvist: ${error.message}`;
      schedule(5000);
    }
  }

  const personNode = document.getElementById("personId");
  if (personNode) {
    new MutationObserver(() => {
      inputValues = {};
      void refresh(true);
    }).observe(personNode, { childList: true, characterData: true, subtree: true });
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) void refresh(true);
  });

  ensureCard();
  void refresh(true);
})();
