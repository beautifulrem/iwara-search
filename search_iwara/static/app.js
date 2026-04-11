/* ===== Theme toggle ===== */
(function initTheme() {
  var toggle = document.getElementById("theme-toggle");
  if (!toggle) return;
  var root = document.documentElement;
  var labels = {
    system: document.body && document.body.dataset.themeSystemLabel ? document.body.dataset.themeSystemLabel : "System",
    dark: document.body && document.body.dataset.themeDarkLabel ? document.body.dataset.themeDarkLabel : "Dark",
    light: document.body && document.body.dataset.themeLightLabel ? document.body.dataset.themeLightLabel : "Light"
  };
  var iconMap = {
    system: "brightness_auto",
    dark: "dark_mode",
    light: "light_mode"
  };

  function getStoredTheme() {
    var stored = localStorage.getItem("theme");
    if (stored === "dark" || stored === "light" || stored === "system") return stored;
    return "system";
  }

  function getEffectiveTheme(mode) {
    if (mode === "dark" || mode === "light") return mode;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function applyTheme(mode) {
    var effective = getEffectiveTheme(mode);
    if (mode === "system") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", effective);
    }
    var icon = toggle.querySelector(".material-symbols-outlined");
    if (icon) icon.textContent = iconMap[mode] || "brightness_auto";
    var label = labels[mode] || labels.system;
    toggle.setAttribute("aria-label", label);
    toggle.setAttribute("title", label);
  }

  function nextTheme(mode) {
    if (mode === "system") return "dark";
    if (mode === "dark") return "light";
    return "system";
  }

  var media = window.matchMedia("(prefers-color-scheme: dark)");
  function syncSystemTheme() {
    var mode = getStoredTheme();
    if (mode === "system") applyTheme("system");
  }

  applyTheme(getStoredTheme());

  toggle.addEventListener("click", function () {
    var next = nextTheme(getStoredTheme());
    localStorage.setItem("theme", next);
    applyTheme(next);
  });

  if (typeof media.addEventListener === "function") {
    media.addEventListener("change", syncSystemTheme);
  } else if (typeof media.addListener === "function") {
    media.addListener(syncSystemTheme);
  }
})();

/* ===== Sidebar toggle ===== */
(function initSidebar() {
  var btn = document.getElementById("sidebar-toggle");
  var sidebar = document.getElementById("sidebar");
  var overlay = document.getElementById("sidebar-overlay");
  if (!btn || !sidebar) return;

  function close() { sidebar.classList.remove("sidebar--open"); }

  btn.addEventListener("click", function () {
    sidebar.classList.toggle("sidebar--open");
  });

  if (overlay) overlay.addEventListener("click", close);
})();

/* ===== Filter panel toggle ===== */
(function initFilterPanel() {
  var btn = document.getElementById("filter-toggle");
  var panel = document.getElementById("filter-panel");
  if (!btn || !panel) return;

  // Auto-open if any chips or filled metric inputs exist
  var hasContent = false;
  panel.querySelectorAll(".chip").forEach(function () { hasContent = true; });
  panel.querySelectorAll(".metrics-grid input").forEach(function (inp) {
    if (inp.value) hasContent = true;
  });
  if (hasContent) panel.classList.add("filter-panel--open");

  btn.addEventListener("click", function () {
    panel.classList.toggle("filter-panel--open");
  });
})();

/* ===== Conflict disabling ===== */
function applyConflictDisabling() {
  var sortHidden = document.getElementById("sort-hidden");
  if (!sortHidden) return;
  var currentSort = sortHidden.value;
  document.querySelectorAll("[data-conflicts]").forEach(function (input) {
    var conflicts = input.dataset.conflicts.split(" ");
    var isConflicting = conflicts.indexOf(currentSort) !== -1;
    var field = input.closest(".field");
    input.disabled = isConflicting;
    if (field) field.classList.toggle("field--disabled", isConflicting);
  });
}

/* ===== Autocomplete chips ===== */
function debounce(fn, delay) {
  var timer = null;
  return function () {
    var args = arguments;
    var ctx = this;
    clearTimeout(timer);
    timer = setTimeout(function () { fn.apply(ctx, args); }, delay);
  };
}

function createChip(id, name, negative) {
  var deleteLabel = document.body && document.body.dataset.deleteLabel ? document.body.dataset.deleteLabel : "Delete";
  var chip = document.createElement("span");
  chip.className = negative ? "chip chip--negative" : "chip";
  chip.dataset.id = String(id);
  chip.textContent = name;

  var button = document.createElement("button");
  button.type = "button";
  button.setAttribute("aria-label", deleteLabel);
  button.textContent = "\u00d7";
  chip.appendChild(button);
  return chip;
}

function mountAutocomplete(root) {
  var hiddenInput = root.querySelector('input[type="hidden"]');
  var input = root.querySelector("[data-autocomplete-input]");
  var chipContainer = root.querySelector("[data-chip-container]");
  var suggestions = root.querySelector("[data-suggestions]");
  var endpoint = root.dataset.api;
  var negative = hiddenInput.name.endsWith("_not");
  var selected = new Map();

  chipContainer.querySelectorAll(".chip").forEach(function (chip) {
    selected.set(chip.dataset.id, chip.firstChild.textContent.trim());
  });

  function syncHiddenValue() {
    hiddenInput.value = Array.from(selected.keys()).join(",");
  }

  function removeChip(id) {
    selected.delete(String(id));
    var target = chipContainer.querySelector('.chip[data-id="' + CSS.escape(String(id)) + '"]');
    if (target) target.remove();
    syncHiddenValue();
  }

  function attachChipEvents(chip) {
    var button = chip.querySelector("button");
    button.addEventListener("click", function () { removeChip(chip.dataset.id); });
  }

  chipContainer.querySelectorAll(".chip").forEach(attachChipEvents);

  function addChip(item) {
    var id = String(item.id);
    if (selected.has(id)) return;
    selected.set(id, item.name);
    var chip = createChip(item.id, item.name, negative);
    chipContainer.appendChild(chip);
    attachChipEvents(chip);
    syncHiddenValue();
  }

  function hideSuggestions() {
    suggestions.hidden = true;
    suggestions.innerHTML = "";
  }

  function fetchSuggestions(query) {
    if (!query.trim()) { hideSuggestions(); return; }
    fetch(endpoint + "?query=" + encodeURIComponent(query))
      .then(function (resp) { return resp.ok ? resp.json() : []; })
      .then(function (items) {
        var filtered = items.filter(function (item) { return !selected.has(String(item.id)); });
        if (!filtered.length) { hideSuggestions(); return; }
        suggestions.innerHTML = "";
        filtered.forEach(function (item) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.textContent = item.name;
          btn.addEventListener("click", function () {
            addChip(item);
            input.value = "";
            hideSuggestions();
          });
          suggestions.appendChild(btn);
        });
        suggestions.hidden = false;
      })
      .catch(function () { hideSuggestions(); });
  }

  var debouncedFetch = debounce(fetchSuggestions, 180);

  input.addEventListener("input", function (e) { debouncedFetch(e.target.value); });
  input.addEventListener("keydown", function (e) { if (e.key === "Escape") hideSuggestions(); });
  document.addEventListener("click", function (e) { if (!root.contains(e.target)) hideSuggestions(); });
}

/* ===== Init ===== */
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("[data-autocomplete-root]").forEach(mountAutocomplete);
  applyConflictDisabling();
});
