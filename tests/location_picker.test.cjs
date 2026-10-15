const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../app/static/location.js"), "utf8");

class Element {
  constructor() { this.value = ""; this.children = []; this.listeners = {}; this.dataset = {}; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  replaceChildren() { this.children = []; }
  append(child) { this.children.push(child); }
  focus() {}
  fire(name, event = {}) { return this.listeners[name]?.(event); }
}

function setup(fetch) {
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const picker = get("picker");
  picker.dataset.searchUrl = "/groups/1/location-search";
  const navigator = { geolocation: {} };
  vm.runInNewContext(source, {
    document: { querySelector: () => picker, getElementById: get, createElement: () => new Element() },
    navigator, fetch, URLSearchParams, AbortController,
  });
  return { get, navigator };
}

(async () => {
  const { get, navigator } = setup(async () => ({ ok: true, json: async () => ({
    sample: false, results: [{ label: "Boston, Massachusetts", latitude: 42.36, longitude: -71.06 }],
  }) }));
  get("location-query").value = "Boston";
  await get("search-location").fire("click");
  assert.equal(get("location-results").children.length, 1);
  get("location-results").children[0].children[0].fire("click");
  assert.equal(get("location-label").value, "Boston, Massachusetts");
  assert.equal(get("location-latitude").value, 42.36);
  get("location-query").value = "Cambridge";
  get("location-query").fire("input");
  assert.equal(get("location-latitude").value, "", "Editing the town must clear old coordinates");
  assert.equal(get("location-label").value, "");

  navigator.geolocation.getCurrentPosition = (success) => success({ coords: { latitude: 42.36123, longitude: -71.06123 } });
  get("approximate-location").fire("click");
  assert.equal(get("location-latitude").value, "42.36");
  assert.equal(get("location-query").value, "Near my current location");
  get("clear-location").fire("click");
  assert.equal(get("location-query").value, "");
  assert.equal(get("location-longitude").value, "");

  navigator.geolocation.getCurrentPosition = (_, failure) => failure();
  get("approximate-location").fire("click");
  assert.match(get("location-status").textContent, /Search for your town/);
  assert.equal(get("approximate-location").disabled, false);

  let resolve;
  const stale = setup(() => new Promise((done) => { resolve = done; }));
  stale.get("location-query").value = "Boston";
  const pending = stale.get("search-location").fire("click");
  stale.get("clear-location").fire("click");
  resolve({ ok: true, json: async () => ({ results: [{ label: "Stale Boston" }] }) });
  await pending;
  assert.equal(stale.get("location-results").children.length, 0, "Late search results must not overwrite a cleared area");
  assert.equal(stale.get("location-query").value, "");
  console.log("Location picker: search, selection, editing, geolocation, clearing, denial, and stale responses passed.");
})().catch((error) => { console.error(error); process.exitCode = 1; });
