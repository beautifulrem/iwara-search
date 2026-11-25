// @ts-check
// Search Iwara — progressive enhancement for the server-rendered UI.
// Every feature degrades to plain links / GET forms when this module does not run.

/** @typedef {{ id: number, name: string, count?: number }} Entity */

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
const THEME_COLORS = { light: "#f8f9fc", dark: "#0b0c0f" };

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
  for (const span of document.querySelectorAll("[data-theme-label]")) {
    span.textContent = label;
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
  const mobileMq = window.matchMedia("(max-width: 39.99rem)");
  for (const form of document.querySelectorAll("[data-sort-form]")) {
    const select = form.querySelector("select");
    const allTpl = form.querySelector("template[data-all-sorts]");
    if (!(form instanceof HTMLFormElement) || !(select instanceof HTMLSelectElement)) continue;
    const desktopNodes = [...select.children].map((node) => node.cloneNode(true));
    const activeSort = select.dataset.activeSort ?? select.value;
    const syncOptions = () => {
      if (!(allTpl instanceof HTMLTemplateElement)) return;
      const source = mobileMq.matches
        ? [...allTpl.content.children].map((node) => node.cloneNode(true))
        : desktopNodes.map((node) => node.cloneNode(true));
      select.replaceChildren(...source);
      select.value = activeSort;
    };
    syncOptions();
    mobileMq.addEventListener("change", syncOptions);
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

/** @typedef {"include" | "require" | "negative"} ChipTone */

/** @param {string} id @param {string} name @param {ChipTone} tone */
function createChip(id, name, tone) {
  const chip = document.createElement("li");
  chip.className =
    tone === "negative" ? "chip chip--negative" : tone === "require" ? "chip chip--require" : "chip";
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
  /** @type {ChipTone} */
  const chipTone = container.classList.contains("combo--negative")
    ? "negative"
    : container.classList.contains("combo--require")
      ? "require"
      : "include";
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

  const parentForm = container.closest("form");

  const syncHidden = () => {
    hidden.value = [...selected.keys()].join(",");
    if (parentForm instanceof HTMLFormElement) syncFilterGroupBadges(parentForm);
  };
  syncHidden();

  const positionPopup = () => {
    const scroller = container.closest(".sheet__body");
    if (scroller instanceof HTMLElement) {
      popup.classList.remove("is-dropup");
      popup.classList.add("is-compact");
      const scrollerRect = scroller.getBoundingClientRect();
      const overflow = popup.getBoundingClientRect().bottom + 8 - scrollerRect.bottom;
      if (overflow > 0) {
        scroller.scrollBy({ top: overflow, behavior: prefersReducedMotion() ? "instant" : "auto" });
      }
      return;
    }
    popup.classList.toggle("is-compact", window.innerHeight - input.getBoundingClientRect().bottom < 240);
  };

  /** @param {boolean} expanded */
  const setExpanded = (expanded) => {
    input.setAttribute("aria-expanded", String(expanded));
    popup.hidden = !expanded;
    if (expanded) {
      positionPopup();
    } else {
      popup.classList.remove("is-dropup", "is-compact");
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
    chips.append(createChip(id, item.name, chipTone));
    syncHidden();
    announce(format(i18n.i18nAdded, { name: item.name }));
  };

  /** @param {number} index */
  const choose = (index) => {
    const item = options[index];
    if (!item) return;
    addChip(item);
    input.value = "";
    if (parentForm instanceof HTMLFormElement) syncFilterGroupBadges(parentForm);
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
      const nameSpan = document.createElement("span");
      nameSpan.className = "combo__option-name";
      nameSpan.append(highlight(item.name, query));
      option.append(nameSpan);
      if (typeof item.count === "number") {
        const countSpan = document.createElement("span");
        countSpan.className = "combo__count";
        countSpan.textContent = item.count.toLocaleString();
        countSpan.setAttribute("aria-hidden", "true");
        option.append(countSpan);
      }
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
      url.searchParams.set("counts", "1");
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
    if (parentForm instanceof HTMLFormElement) syncFilterGroupBadges(parentForm);
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
          if (parentForm instanceof HTMLFormElement) syncFilterGroupBadges(parentForm);
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

  if (parentForm instanceof HTMLFormElement) {
    const resolvers = formResolvers.get(parentForm) ?? [];
    resolvers.push(() => {
      const pending = input.value.trim();
      if (!pending || !options.length) return;
      const picked =
        (active >= 0 ? options[active] : undefined) ??
        options.find((item) => item.name.toLocaleLowerCase() === pending.toLocaleLowerCase()) ??
        (options.length === 1 ? options[0] : undefined);
      if (picked) {
        addChip(picked);
        input.value = "";
      }
    });
    formResolvers.set(parentForm, resolvers);
  }
}

/** @type {WeakMap<HTMLFormElement, Array<() => void>>} */
const formResolvers = new WeakMap();

/** @param {HTMLFormElement} form */
function syncFilterGroupBadges(form) {
  for (const group of form.querySelectorAll("details[data-fgroup]")) {
    if (!(group instanceof HTMLDetailsElement)) continue;
    const badge = group.querySelector("[data-fgroup-badge]");
    if (!(badge instanceof HTMLElement)) continue;
    let count = 0;
    if (group.dataset.fgroup === "entity") {
      count = group.querySelectorAll(".chip").length;
      for (const input of group.querySelectorAll(".combo__input")) {
        if (input instanceof HTMLInputElement && input.value.trim()) count += 1;
      }
    } else if (group.dataset.fgroup === "metrics") {
      for (const range of group.querySelectorAll("fieldset.range")) {
        const hasValue = [...range.querySelectorAll("input")].some(
          (el) => el instanceof HTMLInputElement && el.value.trim() !== "",
        );
        if (hasValue) count += 1;
      }
    }
    badge.textContent = String(count);
    badge.hidden = count === 0;
  }
}

/**
 * @param {HTMLFormElement} form
 * @param {string | undefined} name
 * @returns {HTMLInputElement | null}
 */
function namedInput(form, name) {
  if (!name) return null;
  const el = form.querySelector(`input[name="${CSS.escape(name)}"]`);
  return el instanceof HTMLInputElement ? el : null;
}

/** @param {HTMLFormElement} form */
function syncSheetPresets(form) {
  for (const chip of form.querySelectorAll(".preset-chip[data-preset-field]")) {
    if (!(chip instanceof HTMLElement)) continue;
    const field = namedInput(form, chip.dataset.presetField);
    const clearField = namedInput(form, chip.dataset.presetClear);
    const target = chip.dataset.presetValue ?? "";
    const isActive = Boolean(target) && field?.value.trim() === target && !clearField?.value.trim();
    chip.classList.toggle("is-active", isActive);
    if (isActive) chip.setAttribute("aria-current", "true");
    else chip.removeAttribute("aria-current");
  }
  syncFilterGroupBadges(form);
}

function initFilterForms() {
  for (const form of document.querySelectorAll("form[data-filter-form]")) {
    if (!(form instanceof HTMLFormElement)) continue;
    syncFilterGroupBadges(form);
    form.addEventListener("click", (event) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const chip = event.target instanceof Element ? event.target.closest(".preset-chip[data-preset-field]") : null;
      if (!(chip instanceof HTMLElement)) return;
      const field = namedInput(form, chip.dataset.presetField);
      if (!field) return;
      event.preventDefault();
      const clearField = namedInput(form, chip.dataset.presetClear);
      const target = chip.dataset.presetValue ?? "";
      const wasActive = Boolean(target) && field.value.trim() === target && !clearField?.value.trim();
      field.value = wasActive ? "" : target;
      if (clearField) clearField.value = "";
      const group = field.closest("details");
      if (group instanceof HTMLDetailsElement && !wasActive) group.open = true;
      syncSheetPresets(form);
      announce(chip.textContent?.trim() ?? "");
    });
    form.addEventListener("input", () => syncSheetPresets(form));
    form.addEventListener("change", () => syncSheetPresets(form));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const siteSearch = document.getElementById("site-search");
      const syncedQ = form.querySelector("[data-sync-header-q]");
      if (
        siteSearch instanceof HTMLInputElement &&
        syncedQ instanceof HTMLInputElement &&
        siteSearch.value !== (siteSearch.dataset.initialValue ?? "")
      ) {
        syncedQ.value = siteSearch.value;
      }
      for (const resolvePending of formResolvers.get(form) ?? []) resolvePending();
      const params = new URLSearchParams();
      for (const [key, rawValue] of new FormData(form).entries()) {
        if (typeof rawValue !== "string") continue;
        const value = rawValue.trim();
        if (!value) continue;
        if (key === "sort" && value === "published_desc") continue;
        if (key === "title_mode" && value === "all") continue;
        params.append(key, value);
      }
      startProgress();
      for (const button of form.querySelectorAll('button[type="submit"]')) {
        button.setAttribute("aria-busy", "true");
      }
      const queryString = params.toString();
      window.location.assign(queryString ? `/?${queryString}` : "/");
    });
  }
}

function initHorizontalStrips() {
  const strips = [
    ...document.querySelectorAll(".segmented, .dir-tabs, .active-filters, .active-filters__list"),
  ].filter(
    /** @returns {el is HTMLElement} */ (el) => el instanceof HTMLElement,
  );
  /** @param {HTMLElement} strip */
  const updateEdges = (strip) => {
    const maxScroll = strip.scrollWidth - strip.clientWidth;
    strip.classList.toggle("has-scroll-start", maxScroll > 2 && strip.scrollLeft > 2);
    strip.classList.toggle("has-scroll-end", maxScroll > 2 && strip.scrollLeft < maxScroll - 2);
  };
  for (const strip of strips) {
    if (strip.scrollWidth > strip.clientWidth) {
      const current = strip.querySelector('[aria-current="page"]');
      if (current instanceof HTMLElement) {
        const left = current.offsetLeft - strip.offsetLeft;
        const right = left + current.offsetWidth;
        if (right > strip.clientWidth) {
          strip.scrollLeft = Math.max(0, left - (strip.clientWidth - current.offsetWidth) / 2);
        }
      }
    }
    updateEdges(strip);
    strip.addEventListener("scroll", () => updateEdges(strip), { passive: true });
  }
  window.addEventListener("resize", () => strips.forEach(updateEdges), { passive: true });
}

/** @type {Record<string, [string, string]>} */
const TAX_FIELDS = {
  authors: ["author_any", "author_not"],
  origins: ["origin_any", "origin_not"],
  characters: ["character_any", "character_not"],
  tags: ["tag_all", "tag_not"],
};

/**
 * @param {URLSearchParams} params
 * @param {string} key
 */
const csvIds = (params, key) =>
  (params.get(key) ?? "")
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);

/**
 * @param {URLSearchParams} params
 * @param {string} key
 * @param {string[]} ids
 */
function setCsvIds(params, key, ids) {
  if (ids.length) params.set(key, ids.join(","));
  else params.delete(key);
}

/** @param {string} savedHref */
function enhanceTaxonomyOps(savedHref) {
  const baseParams = new URL(savedHref, window.location.origin).searchParams;
  baseParams.delete("page");
  baseParams.delete("lang");
  for (const link of document.querySelectorAll("a[data-tax-op]")) {
    if (!(link instanceof HTMLAnchorElement)) continue;
    const op = link.dataset.taxOp;
    const kind = link.dataset.taxKind ?? "";
    const id = link.dataset.taxId ?? "";
    const pair = TAX_FIELDS[kind];
    if (!pair || !id || (op !== "inc" && op !== "exc")) continue;
    const [posKey, negKey] = pair;
    const next = new URLSearchParams(baseParams);
    const posIds = csvIds(next, posKey);
    const anyIds = kind === "tags" ? csvIds(next, "tag_any") : [];
    const negIds = csvIds(next, negKey);
    const inPos = posIds.includes(id) || anyIds.includes(id);
    const inNeg = negIds.includes(id);
    if (op === "inc") {
      if (inPos) {
        setCsvIds(next, posKey, posIds.filter((x) => x !== id));
        if (kind === "tags") setCsvIds(next, "tag_any", anyIds.filter((x) => x !== id));
      } else {
        setCsvIds(next, posKey, [...posIds, id].slice(0, 20));
        setCsvIds(next, negKey, negIds.filter((x) => x !== id));
      }
    } else if (inNeg) {
      setCsvIds(next, negKey, negIds.filter((x) => x !== id));
    } else {
      setCsvIds(next, negKey, [...negIds, id].slice(0, 20));
      setCsvIds(next, posKey, posIds.filter((x) => x !== id));
      if (kind === "tags") setCsvIds(next, "tag_any", anyIds.filter((x) => x !== id));
    }
    const qs = next.toString();
    link.href = qs ? `/?${qs}` : "/";
    const active = op === "inc" ? inPos : inNeg;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "true");
    else link.removeAttribute("aria-current");
    const chip = link.closest(".tax-chip");
    if (chip) {
      chip.classList.toggle("is-included", inPos);
      chip.classList.toggle("is-excluded", !inPos && inNeg);
    }
  }
}

function initSearchContext() {
  try {
    const path = window.location.pathname;
    if (path === "/") {
      sessionStorage.setItem("lastSearchHref", `${path}${window.location.search}`);
      return;
    }
    if (!path.startsWith("/movies/")) {
      sessionStorage.removeItem("lastSearchHref");
      return;
    }
    const backLink = document.querySelector("[data-back-search]");
    if (!(backLink instanceof HTMLAnchorElement)) return;
    if (backLink.hasAttribute("data-server-context")) {
      const serverHref = backLink.getAttribute("href");
      if (serverHref && serverHref.startsWith("/") && !serverHref.startsWith("//")) {
        sessionStorage.setItem("lastSearchHref", serverHref);
      }
      return;
    }
    if (document.referrer) {
      const ref = new URL(document.referrer);
      const fromSearchOrDetail =
        ref.origin === window.location.origin && (ref.pathname === "/" || ref.pathname.startsWith("/movies/"));
      if (!fromSearchOrDetail) {
        sessionStorage.removeItem("lastSearchHref");
        return;
      }
    }
    const saved = sessionStorage.getItem("lastSearchHref");
    if (saved && saved.startsWith("/") && !saved.startsWith("//")) {
      backLink.href = saved;
      backLink.hidden = false;
      enhanceTaxonomyOps(saved);
    }
  } catch {
    /* ignore blocked sessionStorage; server-side Referer fallback still works */
  }
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
document.querySelectorAll("[data-combobox]").forEach(initCombobox);
initFilterForms();
initHorizontalStrips();
initSearchContext();
initNavigationFeedback();
initImageFallbacks();

if (prefersReducedMotion()) root.classList.add("reduce-motion");
// Everything above is wired up: tests (and anyone else) can wait for this instead of guessing.
root.classList.add("js-ready");
