function debounce(fn, delay) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}

function createChip(id, name, negative = false) {
  const chip = document.createElement("span");
  chip.className = negative ? "chip chip--negative" : "chip";
  chip.dataset.id = String(id);
  chip.textContent = name;

  const button = document.createElement("button");
  button.type = "button";
  button.setAttribute("aria-label", "删除");
  button.textContent = "×";
  chip.appendChild(button);
  return chip;
}

function mountAutocomplete(root) {
  const hiddenInput = root.querySelector('input[type="hidden"]');
  const input = root.querySelector("[data-autocomplete-input]");
  const chipContainer = root.querySelector("[data-chip-container]");
  const suggestions = root.querySelector("[data-suggestions]");
  const endpoint = root.dataset.api;
  const negative = hiddenInput.name.endsWith("_not");
  const selected = new Map();

  chipContainer.querySelectorAll(".chip").forEach((chip) => {
    selected.set(chip.dataset.id, chip.firstChild.textContent.trim());
  });

  function syncHiddenValue() {
    hiddenInput.value = [...selected.keys()].join(",");
  }

  function removeChip(id) {
    selected.delete(String(id));
    const target = chipContainer.querySelector(`.chip[data-id="${CSS.escape(String(id))}"]`);
    if (target) {
      target.remove();
    }
    syncHiddenValue();
  }

  function attachChipEvents(chip) {
    const button = chip.querySelector("button");
    button.addEventListener("click", () => removeChip(chip.dataset.id));
  }

  chipContainer.querySelectorAll(".chip").forEach(attachChipEvents);

  function addChip(item) {
    const id = String(item.id);
    if (selected.has(id)) {
      return;
    }
    selected.set(id, item.name);
    const chip = createChip(item.id, item.name, negative);
    chipContainer.appendChild(chip);
    attachChipEvents(chip);
    syncHiddenValue();
  }

  function hideSuggestions() {
    suggestions.hidden = true;
    suggestions.replaceChildren();
  }

  async function fetchSuggestions(query) {
    if (!query.trim()) {
      hideSuggestions();
      return;
    }
    const response = await fetch(`${endpoint}?query=${encodeURIComponent(query)}`);
    if (!response.ok) {
      hideSuggestions();
      return;
    }
    const items = await response.json();
    const filtered = items.filter((item) => !selected.has(String(item.id)));
    if (!filtered.length) {
      hideSuggestions();
      return;
    }

    suggestions.replaceChildren();
    filtered.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = item.name;
      button.addEventListener("click", () => {
        addChip(item);
        input.value = "";
        hideSuggestions();
      });
      suggestions.appendChild(button);
    });
    suggestions.hidden = false;
  }

  const debouncedFetch = debounce(fetchSuggestions, 180);

  input.addEventListener("input", (event) => {
    debouncedFetch(event.target.value);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      hideSuggestions();
    }
  });

  document.addEventListener("click", (event) => {
    if (!root.contains(event.target)) {
      hideSuggestions();
    }
  });
}

function applyConflictDisabling() {
  const sortHidden = document.getElementById("sort-hidden");
  if (!sortHidden) return;
  const currentSort = sortHidden.value;
  document.querySelectorAll("[data-conflicts]").forEach((input) => {
    const conflicts = input.dataset.conflicts.split(" ");
    const isConflicting = conflicts.includes(currentSort);
    const field = input.closest(".field");
    input.disabled = isConflicting;
    if (field) field.classList.toggle("field--disabled", isConflicting);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-autocomplete-root]").forEach(mountAutocomplete);
  applyConflictDisabling();
});
