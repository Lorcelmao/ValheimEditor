// Pyodide bootstrap, file in/out, tab rendering, editing. No framework, no
// build step — plain ES module loaded directly by the browser. See
// plans/260912-0936-fch-web-editor-pyodide/phase-04-editing-ui.md.
//
// State lives in Python (a fch_editor.web.bridge.Session), not here: every
// value this file renders comes straight from session.preview()'s JSON
// return, never from a JS-side copy that could drift from what a download
// would actually write. Every edit action (form field committed, item
// removed, "set all" clicked, ...) calls submitEdit()/session.remove_edit()/
// session.discard(), then unconditionally re-renders everything from
// session.preview() and session.list_pending() — success or failure — so a
// rejected edit can never leave a stale or half-applied value on screen.

const bootstrapEl = document.getElementById("bootstrap");
const errorEl = document.getElementById("error-area");
const readingStatusEl = document.getElementById("reading-status");
const dropZoneEl = document.getElementById("drop-zone");
const viewerEl = document.getElementById("viewer");
const fileInput = document.getElementById("file-input");
const fileNameEl = document.getElementById("file-name");
const statusBadgeEl = document.getElementById("status-badge");
const reasonsEl = document.getElementById("reasons-area");
const warningsEl = document.getElementById("warnings-area");
const saveBtn = document.getElementById("save-btn");
const openAnotherBtn = document.getElementById("open-another-btn");
const downloadConfirmationEl = document.getElementById("download-confirmation");
const pendingListEl = document.getElementById("pending-list");
const pendingEmptyEl = document.getElementById("pending-empty");
const discardAllBtn = document.getElementById("discard-all-btn");
const confirmDialog = document.getElementById("confirm-dialog");
const confirmDiffEl = document.getElementById("confirm-diff");
const confirmWriteBtn = document.getElementById("confirm-write-btn");
const confirmCancelBtn = document.getElementById("confirm-cancel-btn");

let pyodide = null; // hoisted out of boot() so submitEdit() can reach pyodide.toPy()
let session = null; // the Python Session, once Pyodide is ready
let catalogData = null; // fetched once after Session() is constructed; never changes per session
let currentFileName = "character.fch";

function setStage(stage) {
  for (const li of bootstrapEl.querySelectorAll("[data-stage]")) {
    li.classList.toggle("done", li.dataset.stage === stage || liIndexBefore(li, stage));
    li.classList.toggle("active", li.dataset.stage === stage);
  }
}

function liIndexBefore(li, stage) {
  const order = ["runtime", "editor", "ready"];
  return order.indexOf(li.dataset.stage) < order.indexOf(stage);
}

function showError(message) {
  errorEl.textContent = message;
  errorEl.hidden = false;
  // The error area sits near the top of the page, but an edit-validation
  // failure can happen while the user is scrolled into a tab further down —
  // without this, "a readable message is shown" would be true in the DOM
  // but not actually visible without scrolling back up.
  errorEl.scrollIntoView({ behavior: "smooth", block: "center" });
}

function clearError() {
  errorEl.hidden = true;
  errorEl.textContent = "";
}

function toJsObj(pyResult) {
  return pyResult.toJs({ dict_converter: Object.fromEntries });
}

async function boot() {
  try {
    setStage("runtime");
    pyodide = await loadPyodide();

    setStage("editor");
    // tools/build_web.ps1 writes this manifest alongside the wheel it just
    // built, so this file never needs to know the wheel's exact filename
    // (which embeds pyproject.toml's version and would otherwise have to be
    // kept in sync by hand).
    const manifest = await fetch(new URL("wheel.json", document.baseURI)).then((r) => r.json());
    const wheelUrl = new URL(manifest.file, document.baseURI).href;
    await pyodide.loadPackage("micropip");
    const micropip = pyodide.pyimport("micropip");
    await micropip.install(wheelUrl);

    const bridge = pyodide.pyimport("fch_editor.web.bridge");
    session = bridge.Session();
    catalogData = toJsObj(session.catalog());

    setStage("ready");
    bootstrapEl.hidden = true;
    dropZoneEl.hidden = false;
  } catch (err) {
    showError(
      "Could not start the editor runtime. This usually means the network request for Pyodide " +
      "or the editor package failed. Reload the page to try again.\n\nDetails: " + err
    );
  }
}

// --- file loading ----------------------------------------------------

async function acceptFile(file) {
  if (!file.name.toLowerCase().endsWith(".fch")) {
    showError(`"${file.name}" doesn't look like a .fch save (wrong extension). Choose a different file.`);
    return;
  }
  clearError();
  currentFileName = file.name;

  // Fourth bootstrap stage ("reading save"): the runtime/editor/ready stages
  // above are already hidden by now, so this is a separate, lightweight
  // indicator rather than reusing that list. The frame yield below matters:
  // session.open() is a synchronous call into Pyodide that blocks the main
  // thread, so without it the browser would never actually paint this text
  // before the parse (usually brief, but not guaranteed for a large or
  // slow-storage file) makes the page look frozen instead.
  readingStatusEl.hidden = false;
  await new Promise(requestAnimationFrame);
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    openBytes(bytes);
  } catch (err) {
    showError(`Could not read "${file.name}" from disk: ${err}`);
  } finally {
    readingStatusEl.hidden = true;
  }
}

function openBytes(bytes) {
  const result = toJsObj(session.open(bytes));
  if (!result.ok) {
    showError(`Could not open "${currentFileName}": ${result.error}`);
    return;
  }
  dropZoneEl.hidden = true;
  viewerEl.hidden = false;
  downloadConfirmationEl.hidden = true;
  // A coordinate chosen while looking at the previous character means nothing
  // here: without this, "Open another" carries the old selection and, worse,
  // an add still aimed at a slot the user picked in a different save.
  resetInventoryViewState();
  refreshAll(); // renders from session.preview(), not from `result` directly -- one source of truth
}

// --- the single re-render entry point ------------------------------------
// Called after open() and after every edit action, success or failure alike,
// so a rejected edit can never leave a stale value on screen (see the
// architecture note at the top of this file).

function refreshAll() {
  const preview = toJsObj(session.preview());
  renderSave(preview.save);
  renderPending(toJsObj(session.list_pending()));
  saveBtn.textContent = preview.changes.length > 0 ? "Save changes" : "Download unchanged";
}

function renderSave(save) {
  fileNameEl.textContent = currentFileName;
  statusBadgeEl.hidden = false;
  statusBadgeEl.textContent = save.writable ? "Writable" : "Read-only";
  statusBadgeEl.className = "badge " + (save.writable ? "badge-ok" : "badge-warn");

  renderList(reasonsEl, "Read-only", save.reasons, "danger");
  renderList(warningsEl, "Warning", save.warnings, "warn");

  renderOverview(save.profile);
  renderSkills(save.profile, save.writable);
  renderCharacter(save.profile, save.writable);
  renderInventory(save.profile, save.writable);
}

function renderList(container, label, items, tone) {
  if (!items || items.length === 0) {
    container.hidden = true;
    container.textContent = "";
    return;
  }
  container.hidden = false;
  container.className = `notice notice-${tone}`;
  container.innerHTML = "";
  for (const item of items) {
    const p = document.createElement("p");
    p.textContent = `${label}: ${item}`;
    container.appendChild(p);
  }
}

// --- element helpers -----------------------------------------------------

// Only these go through property assignment -- confirmed writable IDL props
// we rely on as live state (e.g. .checked toggling, not just an initial
// attribute). Everything else routes through setAttribute, which is also
// the ONLY correct way to set some of them: HTMLInputElement.list, for one,
// is a READ-ONLY IDL property (only the content attribute is settable) --
// assigning to it throws in strict mode (this file is an ES module), which
// would have broken the entire inventory tab's render.
const EL_PROPS = new Set(["value", "checked", "disabled", "selected"]);

function el(tag, opts = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(opts)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (EL_PROPS.has(k)) node[k] = v;
    else node.setAttribute(k, v);
  }
  for (const child of children) node.appendChild(child);
  return node;
}

// `numericCols` (0-based column indices) must right-align a header exactly
// when its own column's body cells are right-aligned (the caller applies
// "num" to those <td>s itself -- see renderSkills/renderInventory). Without
// this, a header stayed left-aligned by default while its numbers sat
// right-aligned in the same, often much wider, auto-sized column: visually
// the two land far apart even though they're the same logical column,
// exactly the "columns don't align" bug a real screenshot caught.
function table(headers, rows, numericCols = []) {
  const wrapper = el("div", { class: "table-wrapper" });
  const t = el("table");
  const thead = el("tr", {}, headers.map((h, i) =>
    el("th", { class: numericCols.includes(i) ? "num" : "", text: h })));
  t.appendChild(el("thead", {}, [thead]));
  const tbody = el("tbody", {}, rows.map((r) => el("tr", {}, r)));
  t.appendChild(tbody);
  wrapper.appendChild(t);
  return wrapper;
}

function selectFromList(options, current, disabled) {
  const select = el("select", { disabled });
  for (const opt of options) {
    const optionEl = el("option", { value: opt, text: opt });
    if (opt === current) optionEl.selected = true;
    select.appendChild(optionEl);
  }
  return select;
}

// Wraps a <input type="number"> with a small themed up/down spinner,
// replacing the browser's native one (hidden via the input[type="number"]
// rules in style.css -- those alone just removed it; this adds a themed
// replacement). Clicking a button adjusts .value using the input's own
// min/max/step, then dispatches a real "change" event so every existing
// commit handler (the submitEdit(...) wiring already on the input) fires
// exactly as if the user had typed and blurred -- no second code path to
// keep in sync with the first.
function numberField(input) {
  const step = () => parseFloat(input.step) || 1; // "any"/unset -> NaN -> nudge by 1
  const bump = (delta) => {
    if (input.disabled) return;
    const current = parseFloat(input.value);
    let next = (Number.isFinite(current) ? current : 0) + delta;
    if (input.min !== "" && next < parseFloat(input.min)) next = parseFloat(input.min);
    if (input.max !== "" && next > parseFloat(input.max)) next = parseFloat(input.max);
    input.value = next;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  };
  // Excluded from tab order (tabindex -1): a type="number" input already
  // steps via the Up/Down arrow keys with no visible spinner needed, so a
  // keyboard user loses nothing -- these buttons are a mouse/touch
  // convenience, and giving them their own tab stops would just add a
  // redundant detour through the same functionality.
  const upBtn = el("button", { type: "button", class: "spin-btn spin-up", "aria-label": "Increase", tabindex: "-1", disabled: input.disabled });
  const downBtn = el("button", { type: "button", class: "spin-btn spin-down", "aria-label": "Decrease", tabindex: "-1", disabled: input.disabled });
  upBtn.addEventListener("click", () => bump(step()));
  downBtn.addEventListener("click", () => bump(-step()));
  return el("span", { class: "number-field" }, [input, el("span", { class: "spin-buttons" }, [upBtn, downBtn])]);
}

let comboBoxIdCounter = 0;

// A themed replacement for <input list="..."> + <datalist>: the native
// popup is rendered by the browser's own UI layer and ignores page styles
// entirely in every major browser, so no CSS fix can make it match a dark
// theme -- this is the only way to fix that (see the design discussion this
// was built from). Implements the ARIA combobox pattern (role="combobox" on
// the input, role="listbox"/"option" on the popup, aria-expanded/
// aria-activedescendant kept in sync) so it is at least as accessible as
// what it replaces, not just visually similar. Filters `options` by
// substring, case-insensitive, capped at 50 shown matches (the dataset
// itself, ~1160 catalog entries, needs no virtualization -- filtering to a
// short list on every keystroke is cheap).
//
// `options` are `{value, label, hint}`: `value` is what lands in the input
// and what an edit spec carries, `label` is what a human recognises, `hint`
// is shown muted beside it. Typing matches against all three, so an item is
// findable by either its in-game name or its prefab codename.
function comboBox(options, placeholder, disabled) {
  const wrapper = el("span", { class: "combobox" });
  const listId = `combobox-list-${comboBoxIdCounter++}`;
  const input = el("input", {
    type: "text", class: "combobox-input", role: "combobox", placeholder,
    "aria-expanded": "false", "aria-autocomplete": "list", "aria-controls": listId,
    autocomplete: "off", disabled,
  });
  const listbox = el("ul", { class: "combobox-list", role: "listbox", id: listId, hidden: true });
  wrapper.appendChild(input);
  wrapper.appendChild(listbox);
  wrapper.input = input; // the caller reads/writes .value and .disabled directly, same as any other field

  let matches = [];
  let activeIndex = -1;
  // Lowercased once per option, not per keystroke: 1,164 entries x 2 fields
  // is enough string work to notice while typing.
  const haystacks = options.map((o) => `${o.label} ${o.value}`.toLowerCase());

  function renderMatches() {
    const q = input.value.trim().toLowerCase();
    matches = [];
    if (q) {
      for (const [i, hay] of haystacks.entries()) {
        if (hay.includes(q)) matches.push(options[i]);
        if (matches.length === 50) break;
      }
    }
    activeIndex = -1;
    listbox.innerHTML = "";
    for (const [i, o] of matches.entries()) {
      const li = el("li", { id: `${listId}-opt-${i}`, role: "option" }, [
        el("span", { class: "combobox-label", text: o.label }),
      ]);
      if (o.hint) li.appendChild(el("span", { class: "combobox-hint mono", text: o.hint }));
      listbox.appendChild(li);
    }
    const open = matches.length > 0;
    listbox.hidden = !open;
    input.setAttribute("aria-expanded", String(open));
    input.removeAttribute("aria-activedescendant");
  }

  function setActive(i) {
    const items = listbox.children;
    if (items[activeIndex]) items[activeIndex].classList.remove("active");
    activeIndex = i;
    if (items[activeIndex]) {
      items[activeIndex].classList.add("active");
      items[activeIndex].scrollIntoView({ block: "nearest" });
      input.setAttribute("aria-activedescendant", items[activeIndex].id);
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function choose(i) {
    if (i < 0 || i >= matches.length) return;
    input.value = matches[i].value;
    close();
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function close() {
    listbox.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    activeIndex = -1;
  }

  input.addEventListener("input", renderMatches);
  input.addEventListener("keydown", (e) => {
    if (listbox.hidden) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") renderMatches();
      return;
    }
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(Math.min(activeIndex + 1, matches.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(Math.max(activeIndex - 1, 0)); }
    else if (e.key === "Enter") { if (activeIndex >= 0) { e.preventDefault(); choose(activeIndex); } }
    else if (e.key === "Escape") { close(); }
  });
  // mousedown, not click: it fires before the input's blur, so the option
  // is still in the DOM (and considered "the thing being interacted with")
  // when chosen by pointer -- a click handler here would lose the race to
  // the blur handler below, which closes the list first.
  listbox.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li");
    if (li) choose(Array.prototype.indexOf.call(listbox.children, li));
  });
  input.addEventListener("blur", () => setTimeout(close, 0));

  return wrapper;
}

// --- editing: the one path every form control commits an edit through ----

function submitEdit(spec) {
  const result = toJsObj(session.add_edit(pyodide.toPy(spec)));
  if (result.ok) {
    clearError();
  } else {
    showError(result.error);
  }
  refreshAll(); // unconditional: see the architecture note at the top of this file
  return result.ok;
}

// --- overview (read-only: no editable fields exist for this section) -----

function renderOverview(profile) {
  const panel = document.querySelector('[data-panel="overview"]');
  panel.innerHTML = "";
  if (!profile) {
    panel.appendChild(el("p", { text: "This save's player data could not be read." }));
    return;
  }
  const rows = [
    ["Name", profile.name],
    ["Character ID", String(profile.player_id)],
    ["Cheats used", profile.used_cheats ? "yes" : "no"],
    ["Profile version", String(profile.version)],
  ];
  panel.appendChild(table(["Field", "Value"],
    rows.map(([k, v]) => [el("td", { text: k }), el("td", { class: "mono", text: v })])));
}

// --- skills ----------------------------------------------------------

function renderSkills(profile, writable) {
  const panel = document.querySelector('[data-panel="skills"]');
  panel.innerHTML = "";
  const skills = profile && profile.player ? profile.player.skills : null;
  if (!skills) {
    panel.appendChild(el("p", { text: "This save's player data could not be read." }));
    return;
  }

  const rows = skills.slice().sort((a, b) => a.name.localeCompare(b.name)).map((s) => {
    // No `max` attribute: the game only caps progression/effect at 100, the
    // stored level itself has no upper bound (see edits/skills.py).
    const levelInput = el("input", { type: "number", step: "any", min: "0", value: f32Text(s.level), class: "mono", disabled: !writable });
    const keepCheckbox = el("input", { type: "checkbox", disabled: !writable });
    levelInput.addEventListener("change", () => {
      const level = parseFloat(levelInput.value);
      if (!Number.isFinite(level)) { showError("Skill level must be a number."); refreshAll(); return; }
      submitEdit({ kind: "skill", skill: s.name, level, keep_progress: keepCheckbox.checked });
    });
    return [
      el("td", { text: s.name }),
      el("td", { class: "mono num" }, [numberField(levelInput)]),
      el("td", { class: "mono num", text: f32Text(s.accumulator) }),
      el("td", {}, [keepCheckbox]),
    ];
  });
  panel.appendChild(table(["Skill", "Level", "Progress", "Keep progress"], rows, [1, 2]));

  const allLevel = el("input", { type: "number", step: "any", min: "0", value: "0", class: "mono", disabled: !writable });
  const allKeep = el("input", { type: "checkbox", disabled: !writable });
  const allBtn = el("button", { type: "button", class: "btn-outline", text: "Apply to all", disabled: !writable });
  allBtn.addEventListener("click", () => {
    const level = parseFloat(allLevel.value);
    if (!Number.isFinite(level)) { showError("Skill level must be a number."); return; }
    submitEdit({ kind: "skill", skill: "all", level, keep_progress: allKeep.checked });
  });
  panel.appendChild(el("div", { class: "set-all-row" }, [
    el("label", { text: "Set every skill to " }, [numberField(allLevel)]),
    el("label", {}, [allKeep, el("span", { text: " keep progress" })]),
    allBtn,
  ]));
}

// --- character ---------------------------------------------------------

function rgbToHex(rgb) {
  const toHex = (v) => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, "0");
  return "#" + rgb.map(toHex).join("");
}

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

function colorField(rgb, writable, onCommit) {
  const input = el("input", { type: "color", value: rgbToHex(rgb), disabled: !writable });
  const readout = el("span", { class: "mono muted", text: ` (${rgb.map(f32Text).join(", ")})` });
  // Fires when the picker closes, not while dragging -- exactly "only send a
  // color edit when the user actually commits a change" (design-system.md's
  // risk note for this control).
  input.addEventListener("change", () => onCommit(hexToRgb(input.value)));
  return el("span", { class: "color-field" }, [input, readout]);
}

function renderCharacter(profile, writable) {
  const panel = document.querySelector('[data-panel="character"]');
  panel.innerHTML = "";
  const p = profile && profile.player;
  if (!p) {
    panel.appendChild(el("p", { text: "This save's player data could not be read." }));
    return;
  }

  const nameInput = el("input", { type: "text", value: profile.name, class: "mono", disabled: !writable });
  nameInput.addEventListener("change", () => {
    if (!nameInput.value.trim()) { showError("Name cannot be empty."); refreshAll(); return; }
    submitEdit({ kind: "name", name: nameInput.value });
  });

  const beardSelect = selectFromList(catalogData.beards, p.beard, !writable);
  beardSelect.addEventListener("change", () => submitEdit({ kind: "beard", style: beardSelect.value }));

  const hairSelect = selectFromList(catalogData.hairs, p.hair, !writable);
  hairSelect.addEventListener("change", () => submitEdit({ kind: "hair", style: hairSelect.value }));

  const skinColor = colorField(p.skin_color, writable, (rgb) => submitEdit({ kind: "color", field: "skin_color", rgb }));
  const hairColor = colorField(p.hair_color, writable, (rgb) => submitEdit({ kind: "color", field: "hair_color", rgb }));

  const modelWrap = el("span", { class: "radio-group" }, [0, 1].map((i) => {
    const radio = el("input", { type: "radio", name: "model-index", value: String(i), checked: p.model_index === i, disabled: !writable });
    radio.addEventListener("change", () => submitEdit({ kind: "model", index: i }));
    return el("label", {}, [radio, el("span", { text: ` ${i} ` })]);
  }));

  // The stored "no power" value is "", but parse_guardian_power (which
  // add_edit's guardian_power builder calls) expects the literal word
  // "none" as input text -- so the synthetic option below uses "none" as
  // its value, not "", and the selected-option match below normalizes the
  // stored "" to "none" to find it.
  const gpOptions = [{ id: "none", name: "none" }, ...catalogData.guardian_powers];
  const gpSelect = el("select", { disabled: !writable }, gpOptions.map((o) => {
    const opt = el("option", { value: o.id, text: o.name });
    if ((p.guardian_power || "none") === o.id) opt.selected = true;
    return opt;
  }));
  gpSelect.addEventListener("change", () => submitEdit({ kind: "guardian_power", power: gpSelect.value }));

  const cooldownInput = el("input", { type: "number", step: "any", min: "0", value: f32Text(p.guardian_power_cooldown), class: "mono", disabled: !writable });
  cooldownInput.addEventListener("change", () => {
    const seconds = parseFloat(cooldownInput.value);
    if (!Number.isFinite(seconds)) { showError("Guardian power cooldown must be a number."); refreshAll(); return; }
    submitEdit({ kind: "guardian_cooldown", seconds });
  });

  const rows = [
    ["Name", nameInput], ["Beard", beardSelect], ["Hair", hairSelect],
    ["Skin color", skinColor], ["Hair color", hairColor], ["Model", modelWrap],
    ["Guardian power", gpSelect], ["Guardian power cooldown (s)", numberField(cooldownInput)],
  ];
  panel.appendChild(table(["Field", "Value"], rows.map(([k, v]) => [el("td", { text: k }), el("td", {}, [v])])));
}

// --- inventory -----------------------------------------------------------

// --- inventory grid --------------------------------------------------------
// The spatial 8xN layout the game itself uses, replacing the flat table.
//
// The selected slot is held as a COORDINATE, never as an element reference:
// refreshAll() rebuilds this whole panel from preview() after every edit, so a
// captured element would be detached from the document the moment the first
// stack change committed, and the detail panel would blank itself on every
// keystroke.
//
// Selecting a slot is a *view* action, so it never re-renders the panel: it
// repaints the slots' selected state and refills the detail box in place.
// Rebuilding everything instead would wipe whatever the user had half-typed
// into the add-item form below, which the table this replaces never did.
let selectedSlot = null;   // {x, y}, or null for nothing selected
let addTargetSlot = null;  // {x, y} the add form is aimed at, or null for "first free slot"

// Both are coordinates chosen while looking at one particular save. Opening
// another one must start clean -- see openBytes().
function resetInventoryViewState() {
  selectedSlot = null;
  addTargetSlot = null;
}

function renderInventory(profile, writable) {
  const panel = document.querySelector('[data-panel="inventory"]');
  panel.innerHTML = "";
  const player = profile && profile.player ? profile.player : null;
  if (!player || !player.items) {
    panel.appendChild(el("p", { text: "This save's player data could not be read." }));
    return;
  }
  const items = player.items;
  // Geometry comes from Python (grid_size clamps invrows and defaults it).
  // If it is somehow absent -- an older cached wheel behind a newer app.js --
  // degrade to "no grid, everything in the list below" rather than throwing:
  // a throw here would abort the rest of refreshAll(), leave the panel blank,
  // and make every item in the save unreachable, which is the exact failure
  // the overflow list exists to prevent.
  const width = player.grid ? player.grid.width : 0;
  const height = player.grid ? player.grid.height : 0;
  if (!player.grid) {
    panel.appendChild(el("div", { class: "notice notice-warn" }, [
      el("strong", { text: "Inventory grid size unavailable. " }),
      el("span", { text: "Showing every item as a list instead. If this persists, reload the page to pick up the current editor build." }),
    ]));
  }

  // A grid that shrank (or a save swapped underneath) can leave a coordinate
  // pointing at a slot that no longer exists.
  if (selectedSlot && (selectedSlot.x >= width || selectedSlot.y >= height)) selectedSlot = null;
  if (addTargetSlot && (addTargetSlot.x >= width || addTargetSlot.y >= height)) addTargetSlot = null;

  // Index by coordinate so each slot is an O(1) lookup instead of a scan of
  // the item list. Anything that can't be placed goes to the list below
  // rather than being dropped: the table this replaces showed every item
  // unconditionally, and silently losing one in a save editor is a
  // correctness bug, not a cosmetic one.
  const byCoord = new Map();
  const overflow = [];
  for (const it of items) {
    const key = `${it.x},${it.y}`;
    const inside = it.x >= 0 && it.x < width && it.y >= 0 && it.y < height;
    if (inside && !byCoord.has(key)) byCoord.set(key, it);
    else overflow.push({ item: it, collision: byCoord.has(key) || items.some((o) => o !== it && o.x === it.x && o.y === it.y) });
  }

  panel.appendChild(el("p", {
    class: "grid-caption",
    text: `${width}x${height} grid, ${items.length} item${items.length === 1 ? "" : "s"}`,
  }));

  const gridEl = el("div", { class: "inv-grid", role: "grid", "aria-label": "Inventory grid", style: `--cols: ${Math.max(width, 1)}` });
  const detailEl = el("div", { class: "slot-detail" });

  const paintSelection = (focusIt) => {
    for (const slotEl of gridEl.querySelectorAll(".inv-slot")) {
      const on = selectedSlot !== null
        && Number(slotEl.dataset.x) === selectedSlot.x && Number(slotEl.dataset.y) === selectedSlot.y;
      slotEl.classList.toggle("selected", on);
      slotEl.setAttribute("aria-selected", on ? "true" : "false");
      // Roving tabindex: the grid is ONE tab stop, not width*height of them.
      slotEl.tabIndex = on ? 0 : -1;
      if (on && focusIt) slotEl.focus();
    }
    if (selectedSlot === null) {
      const first = gridEl.querySelector(".inv-slot");
      if (first) first.tabIndex = 0; // entry point when nothing is selected
    }
    fillSlotDetail(detailEl, byCoord, writable, panel);
  };

  const select = (x, y, focusIt = true) => {
    selectedSlot = { x, y };
    paintSelection(focusIt);
  };

  for (let y = 0; y < height; y++) {
    // display: contents on the row keeps the ARIA row structure without
    // breaking the single CSS grid the cells lay out in.
    const rowEl = el("div", { class: "inv-row", role: "row" });
    for (let x = 0; x < width; x++) {
      rowEl.appendChild(buildSlot(x, y, byCoord.get(`${x},${y}`) || null, select));
    }
    gridEl.appendChild(rowEl);
  }
  gridEl.addEventListener("keydown", (e) => handleGridKeys(e, width, height));
  panel.appendChild(el("div", { class: "inv-grid-wrapper" }, [gridEl]));
  // Re-applies the selection after the full re-render every edit triggers --
  // without stealing focus, since this is not a user selection.
  paintSelection(false);

  if (overflow.length > 0) panel.appendChild(renderOverflow(overflow, width, height, writable));
  panel.appendChild(detailEl);
  panel.appendChild(renderAddItemForm(writable, panel));
  paintAddTarget(panel, writable); // the form's indicator host only exists once it's in the panel
  return panel;
}

function buildSlot(x, y, it, onSelect) {
  const label = it
    ? `Slot ${x},${y}: ${it.display_name}${it.stack > 1 ? `, stack ${it.stack}` : ""}${it.equipped ? ", equipped" : ""}`
    : `Slot ${x},${y}, empty`;
  const slotEl = el("button", {
    type: "button", role: "gridcell", class: `inv-slot${it ? " occupied" : ""}`,
    "aria-label": label, "aria-selected": "false",
    title: it ? `${it.display_name} (${it.name})` : `Empty slot ${x},${y}`,
    tabindex: "-1",
  });
  slotEl.dataset.x = x;
  slotEl.dataset.y = y;
  if (it) {
    slotEl.appendChild(el("span", { class: "slot-name", text: it.display_name }));
    if (it.stack > 1) slotEl.appendChild(el("span", { class: "slot-stack mono", text: String(it.stack) }));
    // Not colour alone: equipped carries a glyph as well as its own styling.
    if (it.equipped) slotEl.appendChild(el("span", { class: "slot-equipped", "aria-hidden": "true", text: "✦" }));
  }
  slotEl.addEventListener("click", () => onSelect(x, y));
  return slotEl;
}

// Arrow keys move between slots; the grid stays one tab stop. Selection
// follows focus, which is what makes the detail panel usable without a mouse.
function handleGridKeys(e, width, height) {
  const deltas = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
  const current = e.target.closest(".inv-slot");
  if (!current) return;
  const x = parseInt(current.dataset.x, 10);
  const y = parseInt(current.dataset.y, 10);
  let next = null;
  if (deltas[e.key]) {
    const [dx, dy] = deltas[e.key];
    next = { x: Math.min(width - 1, Math.max(0, x + dx)), y: Math.min(height - 1, Math.max(0, y + dy)) };
  } else if (e.key === "Home") {
    next = { x: 0, y };
  } else if (e.key === "End") {
    next = { x: width - 1, y };
  } else {
    return; // Enter/Space are the button's own job -- don't intercept them
  }
  e.preventDefault();
  const target = e.currentTarget.querySelector(`.inv-slot[data-x="${next.x}"][data-y="${next.y}"]`);
  if (target) target.click();
}

// Items the grid can't place. Two different reasons, and they are NOT equally
// editable, so the list says which is which: an item at a coordinate outside
// the grid edits and removes normally, but when two items claim the same
// coordinate the Python side refuses to guess which one an edit means
// ("N items occupy slot x,y in this save") -- so those rows show their values
// read-only rather than offering controls that can only ever fail.
function renderOverflow(overflow, width, height, writable) {
  const collisions = overflow.filter((o) => o.collision).length;
  const wrapper = el("div", {});
  const lines = [
    el("strong", { text: `${overflow.length} item${overflow.length === 1 ? "" : "s"} not shown in the ${width}x${height} grid. ` }),
    el("span", { text: "Listed below so nothing is hidden — they are all still in the save. " }),
  ];
  if (collisions > 0) {
    lines.push(el("span", {
      text: `${collisions} share a slot with another item; those cannot be edited or removed here, because an edit by slot would be ambiguous.`,
    }));
  }
  wrapper.appendChild(el("div", { class: "notice notice-warn" }, lines));
  wrapper.appendChild(table(
    ["Slot", "Item", "Stack", "Durability", ""],
    overflow.map(({ item: it, collision }) => {
      if (collision) {
        return [
          el("td", { class: "mono", text: `${it.x},${it.y}` }),
          el("td", {}, itemNameNodes(it)),
          el("td", { class: "mono num", text: String(it.stack) }),
          el("td", { class: "mono num", text: f32Text(it.durability) }),
          el("td", { class: "muted", text: "shared slot" }),
        ];
      }
      const { stackInput, durInput } = itemFieldInputs(it, writable);
      return [
        el("td", { class: "mono", text: `${it.x},${it.y}` }),
        el("td", {}, itemNameNodes(it)),
        el("td", { class: "mono num" }, [numberField(stackInput)]),
        el("td", { class: "mono num" }, [numberField(durInput)]),
        el("td", {}, [removeButton(it, writable)]),
      ];
    }),
    [2, 3],
  ));
  return wrapper;
}

// Display name primary, prefab name secondary -- never only the display name:
// the prefab is the identifier the save, the CLI and `item_add` all speak.
// Collapsed to one line when they're the same string, or when the item isn't
// in the catalog at all (`name` is then #hexhash).
function itemNameNodes(it) {
  return it.display_name === it.name
    ? [el("span", { text: it.name })]
    : [el("span", { text: it.display_name }), el("span", { class: "item-prefab mono", text: it.name })];
}

// Stack and durability commit together as ONE combined item_field edit,
// whichever one changed -- never two independent partial edits for the same
// slot. `edit_key` dedups a pending SetItemField by slot alone and fully
// *replaces* the earlier one on a second add() (by design, and relied on
// elsewhere: see test_edit_state.py), so two separate partial commits
// (stack-only, then durability-only) would silently drop whichever field was
// edited first instead of merging. One function builds both inputs so there
// is no second commit path to keep in sync.
function itemFieldInputs(it, writable) {
  const stackInput = el("input", { type: "number", min: "1", max: "65535", step: "1", value: it.stack, class: "mono", disabled: !writable });
  const durInput = el("input", { type: "number", min: "0", step: "any", value: f32Text(it.durability), class: "mono", disabled: !writable });
  const commit = () => {
    const n = parseInt(stackInput.value, 10);
    if (!Number.isInteger(n)) { showError("Stack must be a whole number."); refreshAll(); return; }
    const d = parseFloat(durInput.value);
    if (!Number.isFinite(d)) { showError("Durability must be a number."); refreshAll(); return; }
    submitEdit({ kind: "item_field", slot: [it.x, it.y], stack: n, durability: d });
  };
  stackInput.addEventListener("change", commit);
  durInput.addEventListener("change", commit);
  return { stackInput, durInput };
}

function removeButton(it, writable) {
  const btn = el("button", { type: "button", class: "btn-outline btn-danger", text: "Remove", disabled: !writable });
  btn.addEventListener("click", () => submitEdit({ kind: "item_remove", slot: [it.x, it.y] }));
  return btn;
}

// The slot is too small to show everything; this box shows all of it. Filled
// in place rather than rebuilt with the panel, so selecting a slot doesn't
// disturb anything else on the tab.
function fillSlotDetail(detailEl, byCoord, writable, panel) {
  detailEl.innerHTML = "";
  if (!selectedSlot) {
    detailEl.appendChild(el("p", { class: "muted", text: "Select a slot to see and edit what's in it." }));
    return;
  }
  const { x, y } = selectedSlot;
  const it = byCoord.get(`${x},${y}`) || null;
  detailEl.appendChild(el("h3", { text: `Slot ${x},${y}` }));

  if (!it) {
    const aimBtn = el("button", { type: "button", class: "btn-outline", text: "Add an item here", disabled: !writable });
    aimBtn.addEventListener("click", () => {
      addTargetSlot = { x, y };
      paintAddTarget(panel);
      const input = panel.querySelector(".combobox-input");
      if (input) input.focus();
    });
    detailEl.appendChild(el("p", { class: "muted", text: "Empty." }));
    detailEl.appendChild(aimBtn);
    return;
  }

  const { stackInput, durInput } = itemFieldInputs(it, writable);
  detailEl.appendChild(el("div", { class: "slot-detail-name" }, itemNameNodes(it)));
  detailEl.appendChild(table(["Quality", "Crafter", "Prefab hash"], [[
    el("td", { class: "mono num", text: String(it.quality) }),
    el("td", { text: it.crafter_name || "—" }),
    el("td", { class: "mono", text: `${it.prefab_hash}` }),
  ]], [0]));
  detailEl.appendChild(el("div", { class: "slot-detail-fields" }, [
    el("label", { text: "Stack " }, [numberField(stackInput)]),
    el("label", { text: " Durability " }, [numberField(durInput)]),
    el("span", { class: "slot-detail-equipped", text: it.equipped ? "Equipped" : "" }),
    removeButton(it, writable),
  ]));
}

// Repaints just the "adding into slot x,y" indicator, so aiming or clearing
// it leaves the rest of the add form -- including anything typed -- alone.
function paintAddTarget(panel, writable = true) {
  const host = panel.querySelector(".add-target");
  if (!host) return;
  host.innerHTML = "";
  if (!addTargetSlot) return;
  const clearBtn = el("button", { type: "button", class: "btn-outline", text: "Clear", disabled: !writable });
  clearBtn.addEventListener("click", () => { addTargetSlot = null; paintAddTarget(panel, writable); });
  host.appendChild(el("span", { text: `Adding into slot ${addTargetSlot.x},${addTargetSlot.y} ` }));
  host.appendChild(clearBtn);
}

function renderAddItemForm(writable, panel) {
  // The prefab name stays the value: it is what `item_add` hashes, and what a
  // user retypes from the CLI or a bug report. The in-game name is the label
  // because "Bronze Plate Tunic" is the only half of the pair most players know.
  const options = catalogData.items.map((it) => ({
    value: it.prefab, label: it.display || it.prefab, hint: it.display ? it.prefab : "",
  }));
  const nameCombo = comboBox(options, "Item name, e.g. Wood or ArmorBronzeChest", !writable);
  const stackInput = el("input", { type: "number", min: "1", max: "65535", step: "1", value: "1", class: "mono", disabled: !writable });
  const durInput = el("input", { type: "number", min: "0", step: "any", value: "100", class: "mono", disabled: !writable });
  const allowUnknown = el("input", { type: "checkbox", disabled: !writable });
  const addBtn = el("button", { type: "button", class: "btn-primary", text: "Add item", disabled: !writable });

  addBtn.addEventListener("click", () => {
    const name = nameCombo.input.value.trim();
    if (!name) { showError("Enter an item name to add."); return; }
    const stack = parseInt(stackInput.value, 10);
    const durability = parseFloat(durInput.value);
    if (!Number.isInteger(stack) || !Number.isFinite(durability)) {
      showError("Stack and durability must be valid numbers.");
      return;
    }
    const spec = { kind: "item_add", name, stack, durability, allow_unknown_item: allowUnknown.checked };
    // AddItem validates occupancy and bounds itself, so an aimed slot is
    // passed straight through rather than pre-checked here in a second place.
    const aimed = addTargetSlot;
    if (aimed) spec.slot = [aimed.x, aimed.y];
    // Cleared before submitting, because submitEdit() re-renders on its own:
    // clearing afterwards would need a second full render just to drop the
    // indicator. Restored if the add was rejected, so the target isn't lost
    // on a fixable error.
    addTargetSlot = null;
    if (!submitEdit(spec)) {
      addTargetSlot = aimed;
      refreshAll();
    }
  });

  const form = el("div", { class: "add-item-form" }, [
    el("h3", { text: "Add item" }),
    el("label", { text: "Name " }, [nameCombo]),
    el("label", { text: " Stack " }, [numberField(stackInput)]),
    el("label", { text: " Durability " }, [numberField(durInput)]),
    el("label", {}, [allowUnknown, el("span", { text: " allow unknown item" })]),
    addBtn,
    el("span", { class: "add-target" }),
  ]);
  return form;
}

// --- pending-changes panel -------------------------------------------------

function renderPending(pendingList) {
  pendingListEl.innerHTML = "";
  if (pendingList.length === 0) {
    pendingEmptyEl.hidden = false;
    discardAllBtn.hidden = true;
    return;
  }
  pendingEmptyEl.hidden = true;
  discardAllBtn.hidden = false;
  pendingList.forEach((entry, index) => {
    const removeBtn = el("button", { type: "button", class: "btn-outline btn-danger", text: "Remove" });
    removeBtn.addEventListener("click", () => {
      session.remove_edit(index); // always safe without re-validation -- see bridge.py's docstring
      refreshAll();
    });
    pendingListEl.appendChild(el("li", {}, [
      el("pre", { class: "mono pending-diff", text: entry.diff_text }),
      removeBtn,
    ]));
  });
}

discardAllBtn.addEventListener("click", () => {
  session.discard();
  refreshAll();
});

// Port of render.f32_text() (Python side): every float this app displays
// (skill level/progress, durability, color components, guardian cooldown) is
// stored as an f32, but `session.preview()`/`open()` hand it over as a plain
// JSON number -- the double-precision value the f32 widens to, e.g.
// 0.800000011920929 for a stored 0.8f. Displaying that raw would be exactly
// the illegible-numbers failure the design system's core principle exists to
// avoid, so this finds the shortest decimal that reproduces the same f32 bit
// pattern, the same way the Python CLI/GUI already display it -- Math.fround
// (round to nearest f32-representable double) stands in for Python's
// F32.pack/unpack round-trip check.
function f32Text(v) {
  if (!Number.isFinite(v)) return String(v);
  const target = Math.fround(v);
  if (target === 0) return Object.is(target, -0) ? "-0" : "0";
  for (let digits = 1; digits <= 9; digits++) {
    const text = target.toPrecision(digits);
    if (Math.fround(parseFloat(text)) === target) return String(parseFloat(text));
  }
  return String(target);
}

// --- tabs --------------------------------------------------------------

for (const tabBtn of document.querySelectorAll('[role="tab"]')) {
  tabBtn.addEventListener("click", () => {
    for (const btn of document.querySelectorAll('[role="tab"]')) {
      btn.setAttribute("aria-selected", String(btn === tabBtn));
    }
    for (const panel of document.querySelectorAll("[data-panel]")) {
      panel.hidden = panel.dataset.panel !== tabBtn.dataset.tab;
    }
  });
}

// --- file input / drag-and-drop -----------------------------------------

fileInput.addEventListener("change", () => {
  if (fileInput.files.length > 0) acceptFile(fileInput.files[0]);
});

for (const target of [dropZoneEl, document.body]) {
  target.addEventListener("dragover", (e) => {
    e.preventDefault();
    if (!dropZoneEl.hidden) dropZoneEl.classList.add("drag-active");
  });
  target.addEventListener("dragleave", () => dropZoneEl.classList.remove("drag-active"));
  target.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZoneEl.classList.remove("drag-active");
    if (!dropZoneEl.hidden && e.dataTransfer.files.length > 0) acceptFile(e.dataTransfer.files[0]);
  });
}

openAnotherBtn.addEventListener("click", () => {
  viewerEl.hidden = true;
  dropZoneEl.hidden = false;
  fileInput.value = "";
  clearError();
  fileNameEl.textContent = "";
  statusBadgeEl.hidden = true;
});

// --- save / confirm / download --------------------------------------------

function renderConfirmDiff(changes) {
  confirmDiffEl.innerHTML = "";
  for (const c of changes) {
    let prefix, tone;
    if (c.old === null || c.old === undefined) { prefix = "+"; tone = "add"; }
    else if (c.new === null || c.new === undefined) { prefix = "-"; tone = "remove"; }
    else { prefix = "~"; tone = "change"; }
    const line = el("div", { class: `diff-line diff-${tone}` });
    line.textContent = `${prefix} ${c.path}: ${fmtDiffValue(c.old)} -> ${fmtDiffValue(c.new)}`;
    confirmDiffEl.appendChild(line);
  }
}

function fmtDiffValue(v) {
  if (v === null || v === undefined) return "—";
  return typeof v === "number" ? f32Text(v) : String(v);
}

function download() {
  const bytes = session.result_bytes().toJs();
  const blob = new Blob([bytes], { type: "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const base = currentFileName.replace(/\.fch$/i, "");
  const a = document.createElement("a");
  a.href = url;
  a.download = `${base}-edited.fch`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  downloadConfirmationEl.hidden = false;
  downloadConfirmationEl.textContent = `Saved as ${base}-edited.fch — check your browser's downloads.`;
}

saveBtn.addEventListener("click", () => {
  const preview = toJsObj(session.preview());
  if (preview.changes.length === 0) {
    // Nothing pending: same as phase 3's always-available round-trip proof,
    // no confirmation needed since there is nothing to confirm.
    download();
    return;
  }
  renderConfirmDiff(preview.changes);
  confirmDialog.showModal();
});

confirmWriteBtn.addEventListener("click", () => {
  confirmDialog.close();
  download();
});

confirmCancelBtn.addEventListener("click", () => confirmDialog.close());
confirmDialog.addEventListener("cancel", () => confirmDialog.close()); // Esc key: also just closes, downloads nothing

boot();
