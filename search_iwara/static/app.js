// @ts-check
// Search Iwara — progressive enhancement for the server-rendered UI.
// Every feature degrades to plain links / GET forms when this module does not run.

/** @typedef {{ id: number, name: string }} Entity */

const root = document.documentElement;
const i18n = document.body.dataset;
const live = document.getElementById("live-region");
const plural = new Intl.PluralRules(root.lang || "en");

/**
 * Replace `{name}` placeholders in a localised template.
 * @param {string | undefined} template
 * @param {Record<string, string | number>} values
 */
const format = (template = "", values = {}) =>
  template.replace(/\{(\w+)\}/g, (_, /** @type {string} */ key) => String(values[key] ?? ""));

/**
 * Pick the CLDR plural form (`data-i18n-<name>-one` / `-other`) for `count`.
 * @param {string} name camel-cased dataset key prefix, e.g. "i18nResults"
 * @param {number} count
 */
const pluralText = (name, count) =>
  i18n[`${name}${plural.select(count) === "one" ? "One" : "Other"}`] ?? i18n[`${name}Other`] ?? "";

/**
 * Politely announce a message to screen readers.
 * @param {string} message
 */
function announce(message) {
  if (!live) return;
  live.textContent = "";
  window.setTimeout(() => {
    live.textContent = message;
  }, 30);
}

const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ------------------------------------------------------------------ theme */

/** @typedef {"system" | "dark" | "light"} ThemePref */

/** @type {ThemePref[]} */
const THEME_ORDER = ["system", "dark", "light"];
const THEME_COLORS = { light: "#f8f8fb", dark: "#101015" };

/** @param {string | undefined} value @returns {ThemePref} */
const asTheme = (value) => (value === "dark" || value === "light" ? value : "system");

/** @param {ThemePref} pref */
function applyTheme(pref) {
  root.dataset.themePref = pref;
  if (pref === "system") delete root.dataset.theme;
  else root.dataset.theme = pref;

  for (const meta of document.querySelectorAll("meta[data-theme-color]")) {
    if (!(meta instanceof HTMLMetaElement)) continue;
    const scheme = meta.dataset.themeColor === "dark" ? "dark" : "light";
    meta.content = pref === "system" ? THEME_COLORS[scheme] : THEME_COLORS[pref];
  }

  const label = i18n[`i18nTheme${pref[0].toUpperCase()}${pref.slice(1)}`] ?? pref;
  for (const button of document.querySelectorAll("[data-theme-toggle]")) {
    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);
  }
}

function initTheme() {
  applyTheme(asTheme(root.dataset.themePref));
  for (const button of document.querySelectorAll("[data-theme-toggle]")) {
    button.addEventListener("click", () => {
      const current = asTheme(root.dataset.themePref);
      const next = THEME_ORDER[(THEME_ORDER.indexOf(current) + 1) % THEME_ORDER.length];
      try {
        if (next === "system") localStorage.removeItem("theme");
        else localStorage.setItem("theme", next);
      } catch {
        /* ignore blocked storage; the choice still applies to this page */
      }
      applyTheme(next);
      announce(button.getAttribute("aria-label") ?? "");
    });
  }
}

/* ---------------------------------------------------------------- dialogs */

// Browsers with Invoker Commands (commandfor/command) open and close dialogs natively; the
// click handlers below are the fallback, guarded so both paths can coexist.
const nativeInvokers = "commandForElement" in HTMLButtonElement.prototype;

function initDialogs() {
  for (const trigger of document.querySelectorAll("[data-dialog-open]")) {
    if (!(trigger instanceof HTMLElement)) continue;
    const dialog = document.getElementById(trigger.dataset.dialogOpen ?? "");
    if (!(dialog instanceof HTMLDialogElement)) continue;
    if (!(nativeInvokers && trigger.hasAttribute("commandfor"))) {
      trigger.addEventListener("click", () => {
        if (!dialog.open) dialog.showModal();
      });
    }
    // Mirror the dialog's `open` attribute onto aria-expanded however it is closed
    // (button, Esc, backdrop). A MutationObserver is synchronous with the attribute change,
    // unlike the `close` event, which browsers may defer for background tabs.
    new MutationObserver(() => trigger.setAttribute("aria-expanded", String(dialog.open))).observe(dialog, {
      attributes: true,
      attributeFilter: ["open"],
    });
  }

  for (const dialog of document.querySelectorAll("dialog")) {
    for (const closer of dialog.querySelectorAll("[data-dialog-close]")) {
      if (nativeInvokers && closer.hasAttribute("commandfor")) continue;
      closer.addEventListener("click", () => dialog.close());
    }
    // Our dialogs have no padding and their content fills the box, so a click whose target
    // is the <dialog> element itself can only have landed on the ::backdrop.
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    // An open autocomplete owns Escape: close the list, not the whole dialog.
    dialog.addEventListener("cancel", (event) => {
      if (dialog.querySelector('[role="combobox"][aria-expanded="true"]')) event.preventDefault();
    });
  }

  // Leaving the mobile breakpoint with the drawer open would strand it on desktop.
  const drawer = document.getElementById("drawer");
  const desktop = window.matchMedia("(min-width: 64rem)");
  desktop.addEventListener("change", (event) => {
    if (event.matches && drawer instanceof HTMLDialogElement && drawer.open) drawer.close();
  });
}

/* --------------------------------------------------------- small helpers */

function initSearchShortcut() {
  const input = document.getElementById("site-search");
  if (!(input instanceof HTMLInputElement)) return;
  document.addEventListener("keydown", (event) => {
    if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
    const target = event.target;
    if (target instanceof HTMLElement && (target.isContentEditable || target.closest("input, textarea, select"))) return;
    if (document.querySelector("dialog[open]")) return;
    event.preventDefault();
    input.focus();
    input.select();
  });
}

function initSortSelect() {
  for (const form of document.querySelectorAll("[data-sort-form]")) {
    const select = form.querySelector("select");
    if (!(form instanceof HTMLFormElement) || !select) continue;
    select.addEventListener("change", () => {
      const href = select.selectedOptions[0]?.dataset.href;
      startProgress();
      if (href) window.location.assign(href);
      else form.requestSubmit();
    });
  }
}

function initCopyButtons() {
  for (const button of document.querySelectorAll("[data-copy]")) {
    if (!(button instanceof HTMLElement)) continue;
    button.addEventListener("click", async () => {
      const source = document.querySelector(button.dataset.copy ?? "");
      if (!source) return;
      try {
        await navigator.clipboard.writeText((source.textContent ?? "").trim());
        button.classList.add("is-done");
        announce(i18n.i18nCopied ?? "");
        window.setTimeout(() => button.classList.remove("is-done"), 1600);
      } catch {
        const range = document.createRange();
        range.selectNodeContents(source);
        const selection = window.getSelection();
        selection?.removeAllRanges();
        selection?.addRange(range);
      }
    });
  }
}

/* --------------------------------------------------- navigation feedback */

function startProgress() {
  root.classList.add("is-navigating");
}

function initNavigationFeedback() {
  for (const form of document.querySelectorAll("form[data-busy-form]")) {
    form.addEventListener("submit", () => {
      startProgress();
      for (const button of form.querySelectorAll('button[type="submit"]')) button.setAttribute("aria-busy", "true");
    });
  }
  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!(link instanceof HTMLAnchorElement) || link.target === "_blank" || link.hasAttribute("download")) return;
    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin || (url.pathname === window.location.pathname && url.hash)) return;
    startProgress();
  });
  // Restored from the back/forward cache: clear any in-flight state.
  window.addEventListener("pageshow", () => {
    root.classList.remove("is-navigating");
    for (const button of document.querySelectorAll('[aria-busy="true"]')) button.removeAttribute("aria-busy");
  });
}

/* ------------------------------------------------------- menus (details) */

function initMenus() {
  const menus = [...document.querySelectorAll("details[data-menu]")].filter(
    /** @returns {menu is HTMLDetailsElement} */ (menu) => menu instanceof HTMLDetailsElement,
  );
  document.addEventListener("click", (event) => {
    for (const menu of menus) {
      if (menu.open && !(event.target instanceof Node && menu.contains(event.target))) menu.open = false;
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    for (const menu of menus) {
      if (menu.open) {
        menu.open = false;
        menu.querySelector("summary")?.focus();
      }
    }
  });
}

/* ----------------------------------------------------------- combobox */

/**
 * Build "before<mark>match</mark>after" with DOM APIs only (never innerHTML).
 * @param {string} text
 * @param {string} query
 */
function highlight(text, query) {
  const fragment = document.createDocumentFragment();
  const index = query ? text.toLocaleLowerCase().indexOf(query.toLocaleLowerCase()) : -1;
  if (index < 0) {
    fragment.append(text);
    return fragment;
  }
  const mark = document.createElement("mark");
  mark.textContent = text.slice(index, index + query.length);
  fragment.append(text.slice(0, index), mark, text.slice(index + query.length));
  return fragment;
}

/** @param {string} id @param {string} name @param {boolean} negative */
function createChip(id, name, negative) {
  const chip = document.createElement("li");
  chip.className = negative ? "chip chip--negative" : "chip";
  chip.dataset.id = String(id);

  const label = document.createElement("span");
  label.className = "chip__label";
  label.textContent = name;

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "chip__remove";
  remove.setAttribute("aria-label", format(i18n.i18nRemove, { name }));
  const template = document.querySelector(".chip__remove svg");
  if (template) remove.append(template.cloneNode(true));
  else remove.textContent = "×";

  chip.append(label, remove);
  return chip;
}

/** @param {Element} container */
function initCombobox(container) {
  if (!(container instanceof HTMLElement)) return;
  const input = container.querySelector('[role="combobox"]');
  const listbox = container.querySelector('[role="listbox"]');
  const popup = container.querySelector(".combo__popup");
  const message = container.querySelector(".combo__message");
  const hidden = container.querySelector("[data-combo-value]");
  const chips = container.querySelector("[data-combo-chips]");
  if (
    !(input instanceof HTMLInputElement) ||
    !(listbox instanceof HTMLElement) ||
    !(popup instanceof HTMLElement) ||
    !(message instanceof HTMLElement) ||
    !(hidden instanceof HTMLInputElement) ||
    !(chips instanceof HTMLElement)
  ) {
    return;
  }

  const api = container.dataset.api ?? "";
  const negative = container.classList.contains("combo--negative");
  /** @type {Map<string, string>} */
  const selected = new Map();
  for (const chip of chips.querySelectorAll(".chip")) {
    if (chip instanceof HTMLElement && chip.dataset.id) {
      selected.set(chip.dataset.id, chip.querySelector(".chip__label")?.textContent ?? "");
    }
  }
  /** @type {Entity[]} */
  let options = [];
  let active = -1;
  /** @type {AbortController | null} */
  let controller = null;
  let timer = 0;
  // Screen-reader announcements of the suggestion count are debounced and only made when
  // the count changes or the list opens, so typing does not flood the live region.
  let announceTimer = 0;
  /** @type {number | null} */
  let announcedCount = null;

  const syncHidden = () => {
    hidden.value = [...selected.keys()].join(",");
  };

  /** @param {boolean} expanded */
  const setExpanded = (expanded) => {
    input.setAttribute("aria-expanded", String(expanded));
    popup.hidden = !expanded;
    if (!expanded) {
      active = -1;
      input.removeAttribute("aria-activedescendant");
      window.clearTimeout(announceTimer);
      announcedCount = null;
    }
  };

  /** @param {number} count */
  const announceCount = (count) => {
    window.clearTimeout(announceTimer);
    if (!input.value.trim() || count === announcedCount) return;
    announceTimer = window.setTimeout(() => {
      announcedCount = count;
      announce(format(pluralText("i18nResults", count), { n: count }));
    }, 500);
  };

  /** @param {string} text */
  const setMessage = (text) => {
    message.textContent = text;
    message.hidden = !text;
  };

  /** @param {number} index */
  const setActive = (index) => {
    const items = [...listbox.children];
    items.forEach((item, i) => item.setAttribute("aria-selected", String(i === index)));
    active = index;
    if (index >= 0 && items[index]) {
      input.setAttribute("aria-activedescendant", items[index].id);
      items[index].scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  };

  /** @param {string} id */
  const removeChip = (id) => {
    const name = selected.get(id);
    selected.delete(id);
    chips.querySelector(`.chip[data-id="${CSS.escape(id)}"]`)?.remove();
    syncHidden();
    if (name) announce(format(i18n.i18nRemoved, { name }));
  };

  /** @param {Entity} item */
  const addChip = (item) => {
    const id = String(item.id);
    if (selected.has(id)) return;
    selected.set(id, item.name);
    chips.append(createChip(id, item.name, negative));
    syncHidden();
    announce(format(i18n.i18nAdded, { name: item.name }));
  };

  /** @param {number} index */
  const choose = (index) => {
    const item = options[index];
    if (!item) return;
    addChip(item);
    input.value = "";
    setExpanded(false);
    input.focus();
  };

  /** @param {string} query */
  const render = (query) => {
    listbox.replaceChildren();
    options.forEach((item, index) => {
      const option = document.createElement("li");
      option.id = `${listbox.id}-${index}`;
      option.className = "combo__option";
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", "false");
      option.append(highlight(item.name, query));
      // mousedown keeps focus in the input so the listbox does not close first.
      option.addEventListener("mousedown", (event) => event.preventDefault());
      option.addEventListener("click", () => choose(index));
      listbox.append(option);
    });
    setMessage(options.length ? "" : i18n.i18nEmpty ?? "");
    setExpanded(true);
    announceCount(options.length);
  };

  /** @param {string} query */
  const load = async (query) => {
    controller?.abort();
    controller = new AbortController();
    setMessage(i18n.i18nLoading ?? "");
    listbox.replaceChildren();
    setExpanded(true);
    container.setAttribute("aria-busy", "true");
    try {
      const url = new URL(api, window.location.origin);
      url.searchParams.set("query", query);
      const response = await fetch(url, { signal: controller.signal, headers: { Accept: "application/json" } });
      /** @type {Entity[]} */
      const items = response.ok ? await response.json() : [];
      options = items.filter((item) => !selected.has(String(item.id)));
      render(query);
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        options = [];
        render(query);
      }
    } finally {
      container.removeAttribute("aria-busy");
    }
  };

  const schedule = () => {
    window.clearTimeout(timer);
    const query = input.value.trim();
    timer = window.setTimeout(() => load(query), 150);
  };

  input.addEventListener("input", schedule);
  input.addEventListener("click", () => {
    if (input.getAttribute("aria-expanded") !== "true") schedule();
  });

  input.addEventListener("keydown", (event) => {
    const expanded = input.getAttribute("aria-expanded") === "true";
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        if (!expanded) schedule();
        else if (options.length) setActive((active + 1) % options.length);
        break;
      case "ArrowUp":
        event.preventDefault();
        if (expanded && options.length) setActive(active <= 0 ? options.length - 1 : active - 1);
        break;
      case "Home":
      case "End":
        if (expanded && options.length) {
          event.preventDefault();
          setActive(event.key === "Home" ? 0 : options.length - 1);
        }
        break;
      case "Enter":
        if (expanded && options.length) {
          event.preventDefault();
          choose(active >= 0 ? active : 0);
        } else if (input.value.trim()) {
          // Typing a name and pressing Enter should never submit the half-built filter.
          event.preventDefault();
          schedule();
        }
        break;
      case "Escape":
        if (expanded) {
          event.preventDefault();
          event.stopPropagation();
          setExpanded(false);
        } else if (input.value) {
          event.preventDefault();
          input.value = "";
        }
        break;
      case "Tab":
        setExpanded(false);
        break;
      case "Backspace":
        if (!input.value && selected.size) {
          const lastId = [...selected.keys()].at(-1);
          if (lastId) removeChip(lastId);
        }
        break;
      default:
        break;
    }
  });

  container.addEventListener("focusout", (event) => {
    const next = event.relatedTarget;
    if (!(next instanceof Node && container.contains(next))) setExpanded(false);
  });

  chips.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest(".chip__remove") : null;
    const chip = button?.closest(".chip");
    if (!(chip instanceof HTMLElement) || !chip.dataset.id) return;
    const next = chip.nextElementSibling?.querySelector(".chip__remove") ?? chip.previousElementSibling?.querySelector(".chip__remove");
    removeChip(chip.dataset.id);
    (next instanceof HTMLElement ? next : input).focus();
  });
}

/* ------------------------------------------------------------------ boot */

function initImageFallbacks() {
  // Images that failed before theme-init.js attached its listener (e.g. from cache).
  // Also mark images that finished loading before the listener existed, so the card scrim shows.
  for (const img of document.querySelectorAll(".media-frame img")) {
    if (!(img instanceof HTMLImageElement) || !img.complete) continue;
    img.closest(".media-frame")?.classList.add(img.naturalWidth === 0 ? "is-broken" : "is-loaded");
  }
}

initTheme();
initDialogs();
initMenus();
initSearchShortcut();
initSortSelect();
initCopyButtons();
initNavigationFeedback();
initImageFallbacks();
document.querySelectorAll("[data-combobox]").forEach(initCombobox);

if (prefersReducedMotion()) root.classList.add("reduce-motion");
// Everything above is wired up: tests (and anyone else) can wait for this instead of guessing.
root.classList.add("js-ready");
