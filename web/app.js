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

function renderInventory(profile, writable) {
  const panel = document.querySelector('[data-panel="inventory"]');
  panel.innerHTML = "";
  const items = profile && profile.player ? profile.player.items : null;
  if (!items) {
    panel.appendChild(el("p", { text: "This save's player data could not be read." }));
    return;
  }

  if (items.length === 0) {
    panel.appendChild(el("p", { text: "No items." }));
  } else {
    const sorted = items.slice().sort((a, b) => (a.y - b.y) || (a.x - b.x));
    const rows = sorted.map((it) => {
      const stackInput = el("input", { type: "number", min: "1", max: "65535", step: "1", value: it.stack, class: "mono", disabled: !writable });
      const durInput = el("input", { type: "number", min: "0", step: "any", value: f32Text(it.durability), class: "mono", disabled: !writable });
      // Both fields commit together as ONE combined item_field edit,
      // whichever one changed -- never two independent partial edits for the
      // same slot. `edit_key` dedups a pending SetItemField by slot alone and
      // fully *replaces* the earlier one on a second add() (by design, and
      // relied on elsewhere: see test_edit_state.py), so two separate
      // partial commits (stack-only, then durability-only) would silently
      // drop whichever field was edited first instead of merging.
      const commitItemField = () => {
        const n = parseInt(stackInput.value, 10);
        if (!Number.isInteger(n)) { showError("Stack must be a whole number."); refreshAll(); return; }
        const d = parseFloat(durInput.value);
        if (!Number.isFinite(d)) { showError("Durability must be a number."); refreshAll(); return; }
        submitEdit({ kind: "item_field", slot: [it.x, it.y], stack: n, durability: d });
      };
      stackInput.addEventListener("change", commitItemField);
      durInput.addEventListener("change", commitItemField);
      const removeBtn = el("button", { type: "button", class: "btn-outline btn-danger", text: "Remove", disabled: !writable });
      removeBtn.addEventListener("click", () => submitEdit({ kind: "item_remove", slot: [it.x, it.y] }));
      return [
        el("td", { class: "mono", text: `${it.x},${it.y}` }),
        // Display name primary, prefab name secondary -- never only the
        // display name: the prefab is the identifier the save, the CLI and
        // `item_add` all speak. Suppressed when they're the same string, or
        // when the item isn't in the catalog at all (`name` is then #hexhash).
        el("td", {}, it.display_name === it.name
          ? [el("span", { text: it.name })]
          : [el("span", { text: it.display_name }),
             el("span", { class: "item-prefab mono", text: it.name })]),
        el("td", { class: "mono num" }, [numberField(stackInput)]),
        el("td", { class: "mono num" }, [numberField(durInput)]),
        el("td", { text: it.equipped ? "yes" : "" }),
        el("td", {}, [removeBtn]),
      ];
    });
    panel.appendChild(table(["Slot", "Item", "Stack", "Durability", "Equipped", ""], rows, [2, 3]));
  }

  panel.appendChild(renderAddItemForm(writable));
}

function renderAddItemForm(writable) {
  // The prefab name stays the value: it is what `item_add` hashes, and what a
  // user retypes from the CLI or a bug report. The in-game name is the label
  // because "Bronze Cuirass" is the only half of the pair most players know.
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
    const ok = submitEdit({ kind: "item_add", name, stack, durability, allow_unknown_item: allowUnknown.checked });
    if (ok) nameCombo.input.value = "";
  });

  return el("div", { class: "add-item-form" }, [
    el("h3", { text: "Add item" }),
    el("label", { text: "Name " }, [nameCombo]),
    el("label", { text: " Stack " }, [numberField(stackInput)]),
    el("label", { text: " Durability " }, [numberField(durInput)]),
    el("label", {}, [allowUnknown, el("span", { text: " allow unknown item" })]),
    addBtn,
  ]);
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
