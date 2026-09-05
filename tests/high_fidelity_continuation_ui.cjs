const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../bodyrig/ui/high_fidelity_continuation.js"), "utf8");
const flush = () => new Promise((resolve) => setImmediate(resolve));

// The card already exists: any subsequent HTML parsing would render API data as markup.
class Element {
  constructor() {
    this.children = [];
    this.text = "";
    this.classList = { add() {}, remove() {} };
  }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map((child) => child.textContent).join(""); }
  set innerHTML(_value) { throw new Error("Status data must be rendered as text"); }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.append(child); }
  replaceChildren(...children) { this.text = ""; this.children = children; }
  addEventListener() {}
}

function studio(...responses) {
  const nodes = new Map();
  for (const id of ["personId", "bodyRevisionLabel", "highFidelityContinuationCard", ...[
    "Summary", "Badge", "Package", "Components", "Gates", "Next", "Production",
  ].map((suffix) => "highFidelityContinuation" + suffix)]) nodes.set(id, new Element());
  nodes.get("personId").textContent = "person-a";
  nodes.get("bodyRevisionLabel").textContent = "body-r0001";
  const observers = new Map();
  const timers = new Map();
  const requests = [];
  let nextTimer = 0;
  vm.runInNewContext(source, {
    document: {
      getElementById: (id) => nodes.get(id),
      createElement: () => new Element(),
      addEventListener() {},
    },
    MutationObserver: class {
      constructor(callback) { this.callback = callback; }
      observe(node) { observers.set(node, this.callback); }
    },
    fetch: async (url, options) => {
      assert.equal(options.cache, "no-store");
      requests.push(url);
      assert.ok(responses.length, "unexpected request: " + url);
      const payload = await responses.shift();
      return { ok: true, json: async () => payload };
    },
    setTimeout: (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, delay }); return id; },
    clearTimeout: (id) => timers.delete(id),
  });
  return {
    nodes, timers, requests, responses,
    text: (suffix) => nodes.get("highFidelityContinuation" + suffix).textContent,
    async poll() {
      assert.equal(timers.size, 1, "one current polling loop");
      const [id, timer] = [...timers][0];
      timers.delete(id);
      timer.callback();
      await flush();
    },
    select(person) {
      const node = nodes.get("personId");
      node.textContent = person;
      observers.get(node)();
    },
  };
}

const preview = { job_id: "hfpreview-" + "a".repeat(32), status: "succeeded" };
const required = {
  state: "incomplete", components: {}, gates: [],
  next_gate: { gate: "eyes_promotion", command: "reviewed eyes command" },
};

test("a preview created after the empty response is discovered without reloading", async () => {
  const ui = studio({}, preview, required);
  await flush();
  assert.equal(ui.text("Badge"), "Preview mangler");
  await ui.poll();
  assert.equal(ui.requests.length, 3);
  assert.match(ui.requests[2], /\/continuation-status$/);
  assert.match(ui.text("Next"), /reviewed eyes command/);
  assert.equal(ui.timers.size, 1);
});

test("invalid review wins over package-complete status and error text cannot become HTML", async () => {
  const markup = '<img src=x onerror="throw new Error(1)">';
  const ui = studio(preview, {
    ...required, state: "blocked", component_package_complete: true,
    gates: [{ id: "review", label: markup, state: "invalid", reason: markup }],
  });
  await flush();
  assert.equal(ui.text("Badge"), "Blokeret");
  assert.equal(ui.text("Summary"), markup);
  assert.ok(ui.text("Gates").includes(markup));
  assert.equal(ui.text("Next"), "");
  assert.match(ui.text("Production"), /blokeret/);
});

test("switching persons immediately clears old readiness and discards a delayed response", async () => {
  const ui = studio(preview, { ...required, software_ready_for_physical_acceptance: true });
  await flush();
  assert.equal(ui.text("Badge"), "SOFTWARE READY");
  let resolveOld;
  ui.responses.push(new Promise((resolve) => { resolveOld = resolve; }));
  ui.select("person-b");
  assert.equal(ui.text("Badge"), "Indlæser");
  assert.equal(ui.text("Next"), "");
  ui.responses.push(preview, required);
  ui.select("person-c");
  await flush();
  assert.match(ui.text("Next"), /eyes_promotion/);
  resolveOld({});
  await flush();
  assert.match(ui.text("Next"), /eyes_promotion/);
  assert.equal(ui.timers.size, 1);
  assert.equal(ui.requests.length, 5);
});

test("an active preview is polled faster until its continuation becomes available", async () => {
  const ui = studio({ ...preview, status: "running" }, preview, required);
  await flush();
  assert.equal(ui.text("Badge"), "Preview kører");
  assert.equal([...ui.timers.values()][0].delay, 2000);
  await ui.poll();
  assert.equal([...ui.timers.values()][0].delay, 5000);
  assert.match(ui.text("Next"), /eyes_promotion/);
});
