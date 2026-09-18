// The Inventory tab's slot grid, driven through a real DOM.
//
// web/app.js talks to the browser, so pytest cannot reach it: these checks load
// the actual app.js against the actual index.html under jsdom, with Pyodide and
// the Python Session stubbed, and drive it the way a user would. They cover what
// the byte-parity tests cannot -- that every item in a save is reachable on
// screen, that an edit sends one combined spec rather than two partial ones, and
// that selection survives the re-render every edit triggers.
//
// Run: npm install && node inventory-grid.test.mjs   (from web/tests/)
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { JSDOM } from "jsdom";

const WEB = path.resolve(import.meta.dirname, "..");
const dom = new JSDOM(fs.readFileSync(path.join(WEB, "index.html"), "utf8"), { pretendToBeVisual: true });
const { window } = dom;
window.Element.prototype.scrollIntoView = () => {};
for (const k of ["window", "document", "Event", "HTMLElement", "Element", "Node", "CustomEvent"]) {
  globalThis[k] = k === "window" ? window : window[k];
}

// The module self-boots into Pyodide on import; strip that and expose the
// internals a test needs to drive it.
const shimPath = path.join(import.meta.dirname, ".app.undertest.mjs");
let src = fs.readFileSync(path.join(WEB, "app.js"), "utf8").replace(/\nboot\(\);\s*$/, "\n");
src += `
export { renderInventory };
export function __set(cat, sess, pyo) { catalogData = cat; session = sess; pyodide = pyo; }
export function __selected() { return selectedSlot; }
export function __addTarget() { return addTargetSlot; }
export { openBytes, resetInventoryViewState };
`;
fs.writeFileSync(shimPath, src);
const app = await import(pathToFileURL(shimPath).href);

const submitted = [];
const py = (v) => ({ toJs: () => v, raw: v });
const catalogStub = {
  items: [{ prefab: "Wood", display: "Wood", type: null },
          { prefab: "ArmorBronzeChest", display: "Bronze Plate Tunic", type: null }],
  beards: ["Beard5"], hairs: ["Hair5"], skills: [{ id: 102, name: "Run" }],
  guardian_powers: [{ id: "GP_Eikthyr", name: "Eikthyr" }],
};
app.__set(
  catalogStub,
  {
    open: () => py({ ok: true }),
    add_edit: (spec) => { submitted.push(spec); return py({ ok: true }); },
    preview: () => py({ changes: [], diff_text: "", save: { writable: true, reasons: [], warnings: [], profile } }),
    list_pending: () => py([]),
  },
  { toPy: (v) => v },
);

const item = (x, y, name, extra = {}) => ({
  x, y, name, display_name: name, stack: 1, durability: 100, equipped: false,
  quality: 1, crafter_name: "", prefab_hash: 123, ...extra,
});

// The other tabs re-render too whenever refreshAll() runs, so the fixture has
// to satisfy them as well -- these fields are not what's under test.
const character = {
  beard: "Beard5", hair: "Hair5", skin_color: [0.5, 0.5, 0.5], hair_color: [0.5, 0.5, 0.5],
  model_index: 0, guardian_power: "", skills: [],
};
const asProfile = (player) => ({ name: "Tester", player_id: 1, used_cheats: false, version: 46, player: { ...character, ...player } });

let profile = asProfile({
    grid: { width: 8, height: 4 },
    items: [
      item(0, 0, "Wood", { stack: 50 }),
      item(7, 3, "Torch", { equipped: true }),
      item(2, 1, "Club"),
      item(9, 9, "LostThing"),        // outside the 8x4 grid
      item(0, 0, "DuplicateClaim"),   // second item on an occupied coordinate
    ],
});

const panel = document.querySelector('[data-panel="inventory"]');
const q = (sel) => panel.querySelectorAll(sel);
let failures = 0;
const check = (label, cond, detail = "") => {
  if (!cond) { failures++; console.log(`  FAIL  ${label}${detail ? ` -- ${detail}` : ""}`); }
  else { console.log(`  ok    ${label}`); }
};

console.log("phase 1 - geometry and rendering");
app.renderInventory(profile, true);
check("renders width*height slots (8x4 = 32)", q(".inv-slot").length === 32);
check("column count comes from the save's geometry", panel.querySelector(".inv-grid").getAttribute("style").includes("--cols: 8"));
check("item at 0,0 is in slot 0,0", q('.inv-slot[data-x="0"][data-y="0"]')[0].textContent.includes("Wood"));
check("item at 7,3 is in slot 7,3", q('.inv-slot[data-x="7"][data-y="3"]')[0].textContent.includes("Torch"));
check("item at 2,1 is in slot 2,1", q('.inv-slot[data-x="2"][data-y="1"]')[0].textContent.includes("Club"));
check("stack > 1 shown on the slot", q('.inv-slot[data-x="0"][data-y="0"]')[0].querySelector(".slot-stack").textContent === "50");
check("equipped marker present", q('.inv-slot[data-x="7"][data-y="3"]')[0].querySelector(".slot-equipped") !== null);
check("empty slot renders with no item text", q('.inv-slot[data-x="5"][data-y="2"]')[0].textContent === "");

const overflowText = panel.querySelector(".notice-warn") ? panel.textContent : "";
check("out-of-grid item is NOT dropped", overflowText.includes("LostThing"));
check("coordinate-collision item is NOT dropped", overflowText.includes("DuplicateClaim"));
check("overflow warning names the count", overflowText.includes("2 items not shown"));
check("every item reachable in the DOM", ["Wood", "Torch", "Club", "LostThing", "DuplicateClaim"]
  .every((n) => panel.textContent.includes(n)));
check("grid is ONE tab stop (roving tabindex)", [...q(".inv-slot")].filter((b) => b.tabIndex === 0).length === 1);

console.log("\nphase 2 - interaction");
q('.inv-slot[data-x="2"][data-y="1"]')[0].click();
check("clicking a slot selects it", app.__selected().x === 2 && app.__selected().y === 1);
check("selected slot is marked", q('.inv-slot[data-x="2"][data-y="1"]')[0].classList.contains("selected"));
check("detail panel shows the item", panel.querySelector(".slot-detail").textContent.includes("Club"));
check("detail panel shows read-only context", panel.querySelector(".slot-detail").textContent.includes("Quality"));

// Arrow key from the selected slot.
const grid = panel.querySelector(".inv-grid");
const ev = (key) => { const e = new window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }); q('.inv-slot.selected')[0].dispatchEvent(e); };
ev("ArrowRight");
check("ArrowRight moves selection", app.__selected().x === 3 && app.__selected().y === 1);
ev("ArrowDown");
check("ArrowDown moves a row", app.__selected().x === 3 && app.__selected().y === 2);
ev("Home");
check("Home goes to the row start", app.__selected().x === 0 && app.__selected().y === 2);
ev("ArrowUp"); ev("ArrowUp"); ev("ArrowUp");
check("ArrowUp clamps at the top edge", app.__selected().y === 0);

// Combined stack+durability commit, the replace-not-merge trap.
q('.inv-slot[data-x="0"][data-y="0"]')[0].click();
const detail = panel.querySelector(".slot-detail");
const [stackInput, durInput] = detail.querySelectorAll("input[type=number]");
submitted.length = 0;
stackInput.value = "7";
stackInput.dispatchEvent(new window.Event("change", { bubbles: true }));
check("one combined item_field edit, not a partial", submitted.length === 1
  && submitted[0].kind === "item_field" && submitted[0].stack === 7 && submitted[0].durability === 100);
check("edit targets the selected slot", JSON.stringify(submitted[0].slot) === "[0,0]");

// Selection must survive the re-render every edit triggers.
app.renderInventory(profile, true);
check("selection survives a re-render", app.__selected().x === 0 && app.__selected().y === 0
  && panel.querySelector(".inv-slot.selected") !== null);

// Empty slot -> aimed add.
q('.inv-slot[data-x="5"][data-y="2"]')[0].click();
check("empty slot detail offers an add", panel.querySelector(".slot-detail").textContent.includes("Empty"));
panel.querySelector(".slot-detail button").click();
check("aiming sets the add target", app.__addTarget().x === 5 && app.__addTarget().y === 2);
check("add form shows the aimed slot", panel.querySelector(".add-item-form").textContent.includes("slot 5,2"));
submitted.length = 0;
panel.querySelector(".combobox-input").value = "Wood";
[...panel.querySelectorAll(".add-item-form button")].find((b) => b.textContent === "Add item").click();
check("add carries the aimed slot", submitted.length === 1 && JSON.stringify(submitted[0].slot) === "[5,2]");

// Read-only save.
app.renderInventory(profile, false);
q('.inv-slot[data-x="0"][data-y="0"]')[0].click();
check("read-only disables every control", [...panel.querySelectorAll("input, button")]
  .filter((n) => !n.classList.contains("inv-slot") && n.type !== "button" || n.classList.contains("btn-danger"))
  .every((n) => n.disabled));

// Geometry actually drives the layout.
profile = asProfile({ grid: { width: 8, height: 7 }, items: [item(0, 6, "DeepSlot")] });
app.renderInventory(profile, true);
check("a 7-row save renders 56 slots", q(".inv-slot").length === 56);
check("item in row 6 is placed, not overflowed", q('.inv-slot[data-x="0"][data-y="6"]')[0].textContent.includes("DeepSlot"));

// Selecting deep, then loading a shallower save, must not leave the selection
// pointing at a slot that no longer exists.
q('.inv-slot[data-x="0"][data-y="6"]')[0].click();
check("deep slot selectable", app.__selected().y === 6);
profile = asProfile({ grid: { width: 8, height: 2 }, items: [item(0, 6, "NowOutside")] });
app.renderInventory(profile, true);
check("stale selection outside the shrunken grid is cleared", app.__selected() === null);
check("an item the shrunken grid can't hold goes to overflow", panel.textContent.includes("NowOutside")
  && panel.querySelector(".notice-warn") !== null);


console.log("\nregression checks (from code review)");

// #1 stale selection / aimed slot must not survive opening another save.
profile = asProfile({ grid: { width: 8, height: 4 }, items: [item(1, 1, "Wood")] });
app.renderInventory(profile, true);
q('.inv-slot[data-x="5"][data-y="2"]')[0].click();
panel.querySelector(".slot-detail button").click();
check("aimed before reopening", app.__addTarget() !== null && app.__selected() !== null);
app.openBytes(new Uint8Array([1, 2, 3]));
check("#1 selection cleared when another save is opened", app.__selected() === null);
check("#1 aimed slot cleared when another save is opened", app.__addTarget() === null);
check("#1 no stale banner", !panel.querySelector(".add-item-form").textContent.includes("Adding into"));

// #2 a missing player.grid must degrade, not throw and blank the panel.
const noGeometry = asProfile({ items: [item(0, 0, "Wood"), item(3, 1, "Torch")] });
let threw = false;
try { app.renderInventory(noGeometry, true); } catch { threw = true; }
check("#2 missing geometry does not throw", threw === false);
check("#2 every item still reachable without geometry",
  panel.textContent.includes("Wood") && panel.textContent.includes("Torch"));
check("#2 degraded state is explained", panel.textContent.includes("grid size unavailable"));

// #3 shared-slot rows must not offer controls that can only ever fail.
profile = asProfile({ grid: { width: 8, height: 4 },
  items: [item(0, 0, "First"), item(0, 0, "Second"), item(9, 9, "FarOut")] });
app.renderInventory(profile, true);
const rows = [...panel.querySelectorAll("table tbody tr")];
const sharedRow = rows.find((r) => r.textContent.includes("Second"));
const outsideRow = rows.find((r) => r.textContent.includes("FarOut"));
check("#3 shared-slot row offers no editable controls", sharedRow.querySelectorAll("input, button").length === 0);
check("#3 shared-slot row says why", sharedRow.textContent.includes("shared slot"));
check("#3 out-of-grid row IS still editable",
  // stack, durability, quality
  outsideRow.querySelectorAll("input").length === 3 && outsideRow.querySelector("button") !== null);
check("#3 notice explains both cases", panel.querySelector(".notice-warn").textContent.includes("cannot be edited"));

// #4 selecting a slot must not wipe a half-typed add form.
profile = asProfile({ grid: { width: 8, height: 4 }, items: [item(0, 0, "Wood")] });
app.renderInventory(profile, true);
panel.querySelector(".combobox-input").value = "ArmorBronzeChest";
panel.querySelectorAll(".add-item-form input[type=number]")[0].value = "42";
q('.inv-slot[data-x="3"][data-y="1"]')[0].click();
check("#4 typed item name survives selecting a slot",
  panel.querySelector(".combobox-input").value === "ArmorBronzeChest");
check("#4 typed stack survives selecting a slot",
  panel.querySelectorAll(".add-item-form input[type=number]")[0].value === "42");
check("#4 selection still took effect", app.__selected().x === 3 && app.__selected().y === 1);

// #5 a successful add must render once, not twice.
let previews = 0;
const countingSession = {
  open: () => py({ ok: true }),
  add_edit: (spec) => { submitted.push(spec); return py({ ok: true }); },
  preview: () => { previews++; return py({ changes: [], diff_text: "", save: { writable: true, reasons: [], warnings: [], profile } }); },
  list_pending: () => py([]),
};
app.__set(catalogStub, countingSession, { toPy: (v) => v });
app.renderInventory(profile, true);
q('.inv-slot[data-x="5"][data-y="2"]')[0].click();
panel.querySelector(".slot-detail button").click();
panel.querySelector(".combobox-input").value = "Wood";
previews = 0;
[...panel.querySelectorAll(".add-item-form button")].find((b) => b.textContent === "Add item").click();
check("#5 successful add renders once", previews === 1, `rendered ${previews}x`);
check("#5 aimed slot cleared after success", app.__addTarget() === null);

// #5b a rejected add must keep the aimed slot rather than losing it.
app.__set(catalogStub, { ...countingSession, add_edit: () => py({ ok: false, error: "slot occupied" }) }, { toPy: (v) => v });
app.renderInventory(profile, true);
q('.inv-slot[data-x="4"][data-y="2"]')[0].click();
panel.querySelector(".slot-detail button").click();
panel.querySelector(".combobox-input").value = "Wood";
[...panel.querySelectorAll(".add-item-form button")].find((b) => b.textContent === "Add item").click();
check("#5b rejected add keeps the aimed slot", app.__addTarget() !== null && app.__addTarget().x === 4);
check("#5b banner still shown after rejection",
  panel.querySelector(".add-item-form").textContent.includes("slot 4,2"));

// #6 read-only must disable EVERY control, buttons included.
app.__set(catalogStub, countingSession, { toPy: (v) => v });
app.renderInventory(profile, false);
q('.inv-slot[data-x="5"][data-y="2"]')[0].click();
const enabled = [...panel.querySelectorAll("button, input")]
  .filter((n) => !n.classList.contains("inv-slot") && !n.classList.contains("spin-btn") && !n.disabled);
check("#6 no enabled control on a read-only save", enabled.length === 0,
  enabled.map((n) => n.textContent || n.type).join(", "));

console.log("\ncopy button");
submitted.length = 0;
// A fresh profile: earlier tests reassign the module-level `profile` variable,
// so this cannot rely on it still containing the Club item used below.
const copyTestProfile = asProfile({
  grid: { width: 8, height: 4 },
  items: [item(2, 1, "Club"), item(0, 0, "First"), item(0, 0, "Second")],  // (0,0) shared, for the overflow check
});
app.__set(catalogStub, {
  open: () => py({ ok: true }),
  add_edit: (spec) => { submitted.push(spec); return py({ ok: true }); },
  preview: () => py({ changes: [], diff_text: "", save: { writable: true, reasons: [], warnings: [], profile: copyTestProfile } }),
  list_pending: () => py([]),
}, { toPy: (v) => v });
app.renderInventory(copyTestProfile, true);
q('.inv-slot[data-x="2"][data-y="1"]')[0].click();  // Club, an ordinary occupied slot
const detailButtons = () => [...panel.querySelector(".slot-detail").querySelectorAll("button")];
const copyBtn = () => detailButtons().find((b) => b.textContent === "Copy");
check("Copy button appears in the detail panel", copyBtn() !== undefined);
copyBtn().click();
check("clicking Copy submits an item_copy spec for the selected slot",
  submitted.length === 1 && submitted[0].kind === "item_copy" && JSON.stringify(submitted[0].slot) === "[2,1]");

// Must never appear on an overflow row: a shared-slot item can't be copied
// (the backend refuses to guess which one is meant), so offering the button
// there would be a control that only ever fails -- the same reasoning that
// already made those rows read-only for Remove.
const overflowButtons = [...panel.querySelectorAll("table tbody tr")]
  .flatMap((row) => [...row.querySelectorAll("button")].map((b) => b.textContent));
check("Copy is absent from the overflow table", !overflowButtons.includes("Copy"), overflowButtons.join(", "));

app.renderInventory(copyTestProfile, false);
q('.inv-slot[data-x="2"][data-y="1"]')[0].click();
check("Copy is disabled on a read-only save", copyBtn().disabled === true);

console.log("\nquality editing");
const qualityProfile = asProfile({
  grid: { width: 8, height: 4 },
  items: [item(2, 1, "Club", { quality: 2 }), item(9, 9, "FarOut", { quality: 3 })],
});
app.__set(catalogStub, {
  open: () => py({ ok: true }),
  add_edit: (spec) => { submitted.push(spec); return py({ ok: true }); },
  preview: () => py({ changes: [], diff_text: "", save: { writable: true, reasons: [], warnings: [], profile: qualityProfile } }),
  list_pending: () => py([]),
}, { toPy: (v) => v });
app.renderInventory(qualityProfile, true);
q('.inv-slot[data-x="2"][data-y="1"]')[0].click();
const detailInputs = () => panel.querySelector(".slot-detail").querySelectorAll("input[type=number]");
check("Quality field appears in the detail panel", detailInputs().length === 3);
const [stackField, , qualityField] = detailInputs();
check("Quality field has no upper cap (unlike Stack, which legitimately has one)",
  !qualityField.max && stackField.max === "65535");
check("hint about the Forge of Potential is shown",
  panel.querySelector(".slot-detail").textContent.includes("Forge of Potential"));

// Combined commit: changing ONE field must still send the CURRENT value of
// every field, never a stale/default one -- a later commit that dropped an
// already-edited field would silently replace it (edit_key dedups
// SetItemField by slot alone, replace-not-merge, a bug this project already
// shipped once).
submitted.length = 0;
qualityField.value = "9";
qualityField.dispatchEvent(new window.Event("change", { bubbles: true }));
check("editing quality sends a combined item_field spec",
  submitted.length === 1 && submitted[0].kind === "item_field"
  && submitted[0].quality === 9 && submitted[0].stack === 1 && typeof submitted[0].durability === "number",
  JSON.stringify(submitted[0]));

submitted.length = 0;
stackField.value = "5";
stackField.dispatchEvent(new window.Event("change", { bubbles: true }));
check("editing stack still carries the just-edited quality along, not the stale original",
  submitted.length === 1 && submitted[0].stack === 5 && submitted[0].quality === 9,
  JSON.stringify(submitted[0]));

submitted.length = 0;
qualityField.value = "0";
qualityField.dispatchEvent(new window.Event("change", { bubbles: true }));
check("quality below 1 is rejected client-side, nothing submitted", submitted.length === 0);

// parseInt("1e3") is 1 and parseInt("7.5") is 7, and both pass Number.isInteger:
// a typed value used to be silently truncated. Quality has no cap to nudge
// anyone toward plain digits, so "1e3" quietly becoming quality 1 mattered.
for (const typed of ["1e3", "7.5", "0x10", "3abc"]) {
  submitted.length = 0;
  qualityField.value = typed;
  qualityField.dispatchEvent(new window.Event("change", { bubbles: true }));
  check(`typed "${typed}" is rejected, not truncated`, submitted.length === 0, JSON.stringify(submitted[0]));
}
submitted.length = 0;
qualityField.value = "12";
qualityField.dispatchEvent(new window.Event("change", { bubbles: true }));
// (No whitespace case: a type="number" input sanitizes " 12 " to "" per the HTML
// spec, so whitespace can never reach the parser. "1e3" and "7.5" above ARE valid
// number-input values, which is exactly why they were getting through.)
check("a plain whole number is still accepted by the strict parser",
  submitted.length === 1 && submitted[0].quality === 12, JSON.stringify(submitted[0]));

// The overflow table gets the same Quality column and the same combined commit.
const overflowRow = [...panel.querySelectorAll("table tbody tr")].find((r) => r.textContent.includes("FarOut"));
check("overflow row has a Quality input", overflowRow.querySelectorAll("input").length === 3);
submitted.length = 0;
const overflowQualityInput = overflowRow.querySelectorAll("input")[2];
overflowQualityInput.value = "7";
overflowQualityInput.dispatchEvent(new window.Event("change", { bubbles: true }));
check("overflow row's quality edit is also combined",
  submitted.length === 1 && submitted[0].quality === 7 && submitted[0].stack === 1, JSON.stringify(submitted[0]));

app.renderInventory(qualityProfile, false);
q('.inv-slot[data-x="2"][data-y="1"]')[0].click();
check("Quality is disabled on a read-only save", [...detailInputs()].every((n) => n.disabled));

fs.unlinkSync(shimPath);
console.log(failures === 0 ? "\nALL CHECKS PASSED" : `\n${failures} CHECK(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
