// The add-item picker, driven through a real DOM.
//
// Companion to inventory-grid.test.mjs -- see that file's header for why these
// exist. The batch-add checks here are the important ones: a partial failure
// must keep its successes, report which items failed, and leave only the
// failures selected. Leaving successes selected made the obvious retry add them
// twice, which reached code review before it was caught.
//
// Run: npm install && node item-picker.test.mjs   (from web/tests/)
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { JSDOM } from "jsdom";

const WEB = path.resolve(import.meta.dirname, "..");
const dom = new JSDOM(fs.readFileSync(path.join(WEB, "index.html"), "utf8"), { pretendToBeVisual: true, url: "https://localhost/" });
const { window } = dom;
window.Element.prototype.scrollIntoView = () => {};
// jsdom implements <dialog> only partially in older versions; stub the modal
// bits so the picker can be driven without them.
if (!window.HTMLDialogElement.prototype.showModal) {
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  window.HTMLDialogElement.prototype.close = function () { this.open = false; };
}
for (const k of ["window", "document", "Event", "HTMLElement", "Element", "Node", "CustomEvent", "localStorage"]) {
  globalThis[k] = k === "window" ? window : window[k];
}

const shimPath = path.join(import.meta.dirname, ".picker.undertest.mjs");
let src = fs.readFileSync(path.join(WEB, "app.js"), "utf8").replace(/\nboot\(\);\s*$/, "\n");
src += `
export { renderInventory, pickerResults, addItems, summarizeFailures };
export function __haystacks() { return pickerHaystacks; }
export function __set(cat, sess, pyo) { catalogData = cat; session = sess; pyodide = pyo; }
export function __selection() { return pickerSelection; }
export function __resetHaystacks() { pickerHaystacks = null; }
export function __addTarget() { return addTargetSlot; }
`;
fs.writeFileSync(shimPath, src);
const app = await import(pathToFileURL(shimPath).href);

const submitted = [];
const py = (v) => ({ toJs: () => v, raw: v });
let addOutcome = () => ({ ok: true });

const catalogStub = {
  items: [
    { prefab: "Wood", display: "Wood", type: null },
    { prefab: "ArmorBronzeChest", display: "Bronze Plate Tunic", type: null },
    { prefab: "AxeStone", display: "Stone Axe", type: null },
    { prefab: "Upgrader3Weapon", display: "Silver Battle Idol", type: null },
    { prefab: "ModItemNoDisplay", display: null, type: null },
  ],
  beards: ["Beard5"], hairs: ["Hair5"], skills: [{ id: 102, name: "Run" }],
  guardian_powers: [{ id: "GP_Eikthyr", name: "Eikthyr" }],
};

const character = {
  beard: "Beard5", hair: "Hair5", skin_color: [0.5, 0.5, 0.5], hair_color: [0.5, 0.5, 0.5],
  model_index: 0, guardian_power: "", skills: [],
};
const item = (x, y, name) => ({
  x, y, name, display_name: name, stack: 1, durability: 100, equipped: false,
  quality: 1, crafter_name: "", prefab_hash: 123,
});
let profile = {
  name: "Tester", player_id: 1, used_cheats: false, version: 46,
  player: { ...character, grid: { width: 8, height: 4 }, items: [item(0, 0, "Wood")] },
};

app.__set(catalogStub, {
  open: () => py({ ok: true }),
  add_edit: (spec) => { submitted.push(spec); return py(addOutcome(spec)); },
  preview: () => py({ changes: [], diff_text: "", save: { writable: true, reasons: [], warnings: [], profile } }),
  list_pending: () => py([]),
}, { toPy: (v) => v });

const panel = document.querySelector('[data-panel="inventory"]');
let failures = 0;
const check = (label, cond, detail = "") => {
  if (!cond) { failures++; console.log(`  FAIL  ${label}${detail ? ` -- ${detail}` : ""}`); }
  else { console.log(`  ok    ${label}`); }
};
const picker = () => document.getElementById("item-picker");
const cards = () => [...picker().querySelectorAll(".picker-card")];
const cardFor = (prefab) => cards().find((c) => c.dataset.prefab === prefab);
const openPicker = () => {
  [...panel.querySelectorAll(".add-item-form button")].find((b) => b.textContent === "Browse\u2026").click();
};
const typeSearch = (text) => {
  const s = picker().querySelector(".picker-search");
  s.value = text;
  picker().refresh(); // bypass the debounce timer
};

console.log("search + sort pipeline (pure function)");
app.__resetHaystacks();
picker;
app.renderInventory(profile, true);
openPicker();
check("Browse opens the picker", picker() !== null && picker().open === true);
check("all catalog items listed by default", cards().length === catalogStub.items.length);
check("sorted by display name", cards()[0].textContent.includes("Bronze Plate Tunic"));

typeSearch("tunic");
check("finds an item by its in-game name", cards().length === 1 && cardFor("ArmorBronzeChest"));
typeSearch("ArmorBronze");
check("finds the same item by its prefab codename", cards().length === 1 && cardFor("ArmorBronzeChest"));
typeSearch("TUNIC");
check("search is case-insensitive", cards().length === 1);
typeSearch("idol");
check("finds a Deep North item added in the catalog refresh", cardFor("Upgrader3Weapon") !== undefined);
typeSearch("ModItem");
check("an item with no display name is still findable by prefab", cardFor("ModItemNoDisplay") !== undefined);

typeSearch("zzzznothing");
check("no-match shows guidance, not a blank grid",
  picker().querySelector(".picker-empty") !== null && picker().querySelector(".picker-empty").hidden === false);
check("guidance is NOT inside the listbox (it would go unannounced)",
  picker().querySelector(".picker-grid .picker-empty") === null);
check("no-match points at the free-text escape hatch",
  picker().querySelector(".picker-empty").textContent.includes("allow unknown item"));
check("result count is announced", picker().querySelector(".picker-count").getAttribute("aria-live") === "polite");

typeSearch("");
check("clearing the search restores every item", cards().length === catalogStub.items.length);

console.log("\nselection");
cardFor("Wood").click();
check("clicking a card selects it", app.__selection().has("Wood"));
check("selected card is marked", cardFor("Wood").classList.contains("selected"));
check("selection is not colour-alone (aria-selected)", cardFor("Wood").getAttribute("aria-selected") === "true");
cardFor("AxeStone").click();
check("multi-select accumulates", app.__selection().size === 2);
check("footer counts the selection", picker().querySelector(".picker-selection").textContent === "2 selected");
cardFor("Wood").click();
check("clicking again deselects", app.__selection().has("Wood") === false && app.__selection().size === 1);
picker().querySelector(".picker-foot .btn-outline").click();
check("Clear empties the selection", app.__selection().size === 0);
check("Add is disabled with nothing selected",
  [...picker().querySelectorAll(".picker-foot button")].find((b) => b.textContent.startsWith("Add")).disabled);

console.log("\nselection survives filtering");
cardFor("Wood").click();
typeSearch("axe");
cardFor("AxeStone").click();
typeSearch("");
check("a selection made before filtering is still selected after",
  app.__selection().has("Wood") && app.__selection().has("AxeStone"));
check("both show as selected once visible again",
  cardFor("Wood").classList.contains("selected") && cardFor("AxeStone").classList.contains("selected"));

console.log("\nadding");
submitted.length = 0;
const addBtn = () => [...picker().querySelectorAll(".picker-foot button")].find((b) => b.textContent.startsWith("Add"));
check("button names the count", addBtn().textContent === "Add 2 items");
addBtn().click();
check("N selections produce N item_add edits", submitted.length === 2 && submitted.every((s) => s.kind === "item_add"));
check("each edit carries the prefab name, not the display name",
  submitted.map((s) => s.name).sort().join(",") === "AxeStone,Wood");
check("form's stack/durability apply to every item",
  submitted.every((s) => s.stack === 1 && s.durability === 100));
check("picker closes after a clean add", picker().open === false);

console.log("\npartial failure (inventory fills mid-batch)");
app.renderInventory(profile, true);
openPicker();
cardFor("Wood").click();
cardFor("AxeStone").click();
cardFor("ArmorBronzeChest").click();
submitted.length = 0;
let n = 0;
addOutcome = () => (++n === 1 ? { ok: true } : { ok: false, error: "inventory is full" });
addBtn().click();
check("every item was attempted", submitted.length === 3);
check("successes are kept, not rolled back", n === 3);
check("picker stays open so the selection isn't lost", picker().open === true);

// C1: the retry must not re-add what already succeeded.
const failureNote = picker().querySelector(".picker-failures");
check("failure report is INSIDE the dialog, not behind the backdrop",
  failureNote !== null && failureNote.hidden === false && picker().contains(failureNote));
check("report names the items that failed",
  failureNote.textContent.includes("Stone Axe") || failureNote.textContent.includes("AxeStone"),
  failureNote.textContent);
check("report says why", failureNote.textContent.includes("inventory is full"));
check("report counts what landed", failureNote.textContent.includes("1 of 3 added"));
check("only the FAILED items stay selected", app.__selection().size === 2);
check("the item that succeeded is deselected", app.__selection().has("Wood") === false);
check("search is cleared so the failures are visible", picker().querySelector(".picker-search").value === "");

submitted.length = 0;
addOutcome = () => ({ ok: true });
addBtn().click();
check("retry re-adds ONLY the failures, never duplicating a success",
  submitted.length === 2 && !submitted.some((x) => x.name === "Wood"),
  submitted.map((x) => x.name).join(","));
check("picker closes once the retry succeeds", picker().open === false);

// H2: the picker must not submit values from a form the user can no longer see.
console.log("\nstale form values");
app.renderInventory(profile, true);
panel.querySelectorAll(".add-item-form input[type=number]")[0].value = "42";
openPicker();
cardFor("Wood").click();
cardFor("AxeStone").click();
submitted.length = 0;
n = 0;
addOutcome = () => (++n === 1 ? { ok: false, error: "inventory is full" } : { ok: true });
addBtn().click();
const visibleStack = panel.querySelectorAll(".add-item-form input[type=number]")[0].value;
submitted.length = 0;
addOutcome = () => ({ ok: true });
addBtn().click();
check("the second submit uses the values the form currently SHOWS",
  String(submitted[0].stack) === visibleStack,
  `submitted ${submitted[0].stack}, form shows ${visibleStack}`);

// M1: the aimed slot belongs to the first item only.
console.log("\naimed slot accounting");
app.renderInventory(profile, true);
document.querySelector('.inv-slot[data-x="5"][data-y="2"]').click();
panel.querySelector(".slot-detail button").click();
check("aimed at 5,2", app.__addTarget() !== null);
openPicker();
cardFor("Wood").click();
cardFor("AxeStone").click();
n = 0;
addOutcome = () => (++n === 1 ? { ok: false, error: "slot 5,2 is occupied" } : { ok: true });
addBtn().click();
check("aim is kept when the FIRST item (the only one that could use it) failed",
  app.__addTarget() !== null && app.__addTarget().x === 5);
addOutcome = () => ({ ok: true });
picker().close();

app.renderInventory(profile, true);
document.querySelector('.inv-slot[data-x="4"][data-y="2"]').click();
panel.querySelector(".slot-detail button").click();
openPicker();
cardFor("Wood").click();
cardFor("AxeStone").click();
n = 0;
addOutcome = () => (++n === 2 ? { ok: false, error: "inventory is full" } : { ok: true });
addBtn().click();
check("aim is consumed when the first item DID land in it", app.__addTarget() === null);
addOutcome = () => ({ ok: true });
picker().close();

console.log("\nrecently used");
picker().close();
app.renderInventory(profile, true);
openPicker();
const sortBtn = (label) => [...picker().querySelectorAll(".picker-sort-btn")].find((b) => b.textContent === label);
sortBtn("Recently used").click();
check("sort mode is reflected in aria-pressed", sortBtn("Recently used").getAttribute("aria-pressed") === "true");
check("previously added items float to the top",
  ["Wood", "AxeStone"].includes(cards()[0].dataset.prefab), cards()[0].dataset.prefab);
check("the rest of the catalog is still listed", cards().length === catalogStub.items.length);
sortBtn("Name").click();
check("switching back to Name re-sorts", cards()[0].textContent.includes("Bronze Plate Tunic"));

console.log("\nrecents reflect reality");
localStorage.removeItem("fch-editor.recent-items");
app.renderInventory(profile, true);
openPicker();
cardFor("Wood").click();
addOutcome = () => ({ ok: false, error: "inventory is full" });
addBtn().click();
check("a wholly failed batch records nothing as recently used",
  localStorage.getItem("fch-editor.recent-items") === null,
  String(localStorage.getItem("fch-editor.recent-items")));
addOutcome = () => ({ ok: true });
picker().close();

app.renderInventory(profile, true);
panel.querySelector(".combobox-input").value = "AxeStone";
[...panel.querySelectorAll(".add-item-form button")].find((b) => b.textContent === "Add item").click();
check("a successful typed add IS remembered",
  (localStorage.getItem("fch-editor.recent-items") || "").includes("AxeStone"));

console.log("\nrecents degrade safely");
localStorage.setItem("fch-editor.recent-items", "{not json");
let threw = false;
try { picker().refresh(); } catch { threw = true; }
check("corrupt storage does not throw", threw === false);
localStorage.setItem("fch-editor.recent-items", JSON.stringify(["NoLongerInCatalog", "Wood"]));
sortBtn("Recently used").click();
check("stale recents are filtered against the live catalog",
  cards().length === catalogStub.items.length && !cardFor("NoLongerInCatalog"));

console.log("\nkeyboard");
sortBtn("Name").click();
const key = (el, k) => el.dispatchEvent(new window.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true }));
check("grid is one tab stop", cards().filter((c) => c.tabIndex === 0).length === 1);
key(picker().querySelector(".picker-search"), "ArrowDown");
check("ArrowDown from search enters the grid", document.activeElement.classList.contains("picker-card"));
key(document.activeElement, "ArrowRight");
check("ArrowRight moves focus", document.activeElement === cards()[1]);
key(document.activeElement, "End");
check("End jumps to the last card", document.activeElement === cards()[cards().length - 1]);
key(document.activeElement, "Home");
check("Home jumps to the first card", document.activeElement === cards()[0]);
check("roving tabindex still leaves one tab stop", cards().filter((c) => c.tabIndex === 0).length === 1);

console.log("\nthe typed field still works");
picker().close();
app.renderInventory(profile, true);
submitted.length = 0;
panel.querySelector(".combobox-input").value = "SomeUnknownModPrefab";
panel.querySelector(".add-item-form input[type=checkbox]").checked = true;
[...panel.querySelectorAll(".add-item-form button")].find((b) => b.textContent === "Add item").click();
check("free-text add still submits", submitted.length === 1 && submitted[0].name === "SomeUnknownModPrefab");
check("allow_unknown_item is carried", submitted[0].allow_unknown_item === true);

console.log("\nread-only");
app.renderInventory(profile, false);
check("Browse is disabled on a read-only save",
  [...panel.querySelectorAll(".add-item-form button")].find((b) => b.textContent === "Browse\u2026").disabled);

// The pure pipeline, exercised directly.
console.log("\npipeline function");
const hays = app.__haystacks();
const sorted = app.pickerResults(catalogStub.items, hays, "", "name", []);
check("pipeline sorts by display name", sorted[0].prefab === "ArmorBronzeChest");
check("pipeline filters", app.pickerResults(catalogStub.items, hays, "axe", "name", []).length === 1);
check("pipeline is pure (input untouched)", catalogStub.items[0].prefab === "Wood");

fs.unlinkSync(shimPath);
console.log(failures === 0 ? "\nALL CHECKS PASSED" : `\n${failures} CHECK(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
