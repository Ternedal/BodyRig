(() => {
  const VIEW_LABELS = {
    "front-full": "Front · helfigur",
    "three-quarter-full": "¾ · helfigur",
    "side-full": "Side · helfigur",
    "face-front": "Ansigt · front",
  };
  let requestSerial = 0;
  let lastKey = "";

  function currentPersonId() {
    return (document.getElementById("personId")?.textContent || "").trim();
  }

  function currentBodyRevision() {
    const value = (document.getElementById("bodyRevisionLabel")?.textContent || "").trim();
    return value.startsWith("body-r") ? value : "";
  }

  function ensureCard() {
    let card = document.getElementById("bodyReviewGalleryCard");
    if (card) return card;
    const tab = document.getElementById("tab-body");
    if (!tab) return null;
    card = document.createElement("article");
    card.id = "bodyReviewGalleryCard";
    card.className = "card space-top";
    card.innerHTML = `
      <div class="card-row">
        <div>
          <div class="card-label">Fidelity review · 4 views</div>
          <div id="bodyReviewGallerySummary" class="muted-text">Ingen body-revision valgt.</div>
        </div>
        <span id="bodyReviewGalleryBadge" class="badge muted">Ingen review</span>
      </div>
      <div id="bodyReviewGalleryGrid" class="body-review-grid"></div>
      <p id="bodyReviewGalleryDetail" class="fine-print">De fire views er renderer-captures bundet til den eksakte .mrbody package SHA. De er visuel fidelity-evidence, ikke identitetsverifikation eller production acceptance.</p>`;
    const split = tab.querySelector(":scope > .split");
    if (split) split.insertAdjacentElement("afterend", card);
    else tab.prepend(card);
    return card;
  }

  function nodes() {
    ensureCard();
    return {
      summary: document.getElementById("bodyReviewGallerySummary"),
      badge: document.getElementById("bodyReviewGalleryBadge"),
      grid: document.getElementById("bodyReviewGalleryGrid"),
      detail: document.getElementById("bodyReviewGalleryDetail"),
    };
  }

  function reset(message, badgeText = "Ingen review") {
    const { summary, badge, grid, detail } = nodes();
    if (!summary || !badge || !grid || !detail) return;
    summary.textContent = message;
    badge.textContent = badgeText;
    badge.classList.add("muted");
    grid.replaceChildren();
    detail.textContent = "De fire views er renderer-captures bundet til den eksakte .mrbody package SHA. De er visuel fidelity-evidence, ikke identitetsverifikation eller production acceptance.";
  }

  async function apiJson(url) {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const detail = payload && typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`;
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function renderReview(review, serial) {
    const { summary, badge, grid, detail } = nodes();
    if (!summary || !badge || !grid || !detail) return;
    const views = Array.isArray(review.views) ? review.views : [];
    if (views.length !== 4) {
      reset("Review-kontrakten returnerede ikke fire canonical views.", "Review ugyldig");
      return;
    }

    grid.replaceChildren();
    summary.textContent = `${review.body_revision} · ${review.body_id} · package ${String(review.package_sha256 || "").slice(0, 16)}…`;
    badge.textContent = "Validerer 4 views";
    badge.classList.add("muted");
    detail.textContent = `BodyRig ${review.bodyrig_revision || "?"} · ${review.semantics || "visual fidelity review"}. Hvert image-request genvaliderer persisted review-evidence og .mrbody-bytes.`;

    let loaded = 0;
    let failed = false;
    for (const view of views) {
      const expected = VIEW_LABELS[view.view];
      if (!expected || typeof view.url !== "string" || typeof view.sha256 !== "string") {
        reset("Review-kontrakten indeholder et ukendt eller ufuldstændigt view.", "Review ugyldig");
        return;
      }
      const figure = document.createElement("figure");
      figure.className = "body-review-view";
      const image = document.createElement("img");
      image.alt = `${expected} · ${review.body_revision}`;
      image.decoding = "async";
      image.loading = "lazy";
      image.src = `${view.url}${view.url.includes("?") ? "&" : "?"}v=${encodeURIComponent(view.sha256)}`;
      const caption = document.createElement("figcaption");
      const title = document.createElement("strong");
      title.textContent = expected;
      const meta = document.createElement("span");
      meta.textContent = `${view.width}×${view.height} · ${view.sha256.slice(0, 12)}…`;
      caption.append(title, meta);
      figure.append(image, caption);
      grid.appendChild(figure);

      image.addEventListener("load", () => {
        if (serial !== requestSerial || failed) return;
        loaded += 1;
        if (loaded === views.length) {
          badge.textContent = "4/4 hash-bundet";
          badge.classList.remove("muted");
        }
      });
      image.addEventListener("error", () => {
        if (serial !== requestSerial) return;
        failed = true;
        badge.textContent = "Review ugyldig";
        badge.classList.add("muted");
        detail.textContent = "Fail-closed: mindst ét canonical review-image kunne ikke genvalideres mod persisted evidence og den registrerede body revision.";
      });
    }
  }

  async function refresh(force = false) {
    ensureCard();
    const personId = currentPersonId();
    const revision = currentBodyRevision();
    const key = `${personId}|${revision}`;
    if (!force && key === lastKey) return;
    lastKey = key;
    const serial = ++requestSerial;

    if (!personId) {
      reset("Ingen person valgt.");
      return;
    }
    if (!revision) {
      reset("Ingen body-revision endnu.");
      return;
    }

    const { summary, badge, grid } = nodes();
    if (summary) summary.textContent = `${revision} · kontrollerer package-bound review-evidence…`;
    if (badge) {
      badge.textContent = "Kontrollerer";
      badge.classList.add("muted");
    }
    if (grid) grid.replaceChildren();

    try {
      const review = await apiJson(`/api/v1/people/${encodeURIComponent(personId)}/body/review?revision=${encodeURIComponent(revision)}`);
      if (serial !== requestSerial || currentPersonId() !== personId || currentBodyRevision() !== revision) return;
      renderReview(review, serial);
    } catch (error) {
      if (serial !== requestSerial) return;
      if (error.status === 404) {
        reset(`${revision} har ingen autoritativ multi-view review-evidence.`, "Review mangler");
      } else {
        reset(`Kunne ikke validere review for ${revision}: ${error.message}`, "Review ugyldig");
      }
    }
  }

  for (const id of ["personId", "bodyRevisionLabel"]) {
    const node = document.getElementById(id);
    if (node) {
      new MutationObserver(() => { void refresh(); }).observe(node, {
        childList: true,
        characterData: true,
        subtree: true,
      });
    }
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) void refresh(true);
  });
  ensureCard();
  void refresh(true);
})();

// High-fidelity hair/eye review is an isolated extension. A load failure must not
// break the baseline package-bound four-view gallery above.
void import("/ui/high_fidelity_preview.js").catch((error) => {
  console.error("BodyRig high-fidelity preview UI could not be loaded", error);
});
