// @ts-check
// Runs synchronously in <head>, before first paint: applies the saved theme (no flash) and
// marks the document as JS-enabled. It also catches thumbnail load errors that happen
// before the deferred app module is ready, so broken images never show raw alt text.
(() => {
  const root = document.documentElement;
  root.classList.replace("no-js", "js");
  let pref = "system";
  try {
    const stored = localStorage.getItem("theme");
    if (stored === "dark" || stored === "light") pref = stored;
  } catch {
    /* storage may be blocked; fall back to the system preference */
  }
  root.dataset.themePref = pref;
  if (pref !== "system") root.dataset.theme = pref;

  /** @param {string} className */
  const onMedia = (className) => (/** @type {Event} */ event) => {
    const target = event.target;
    if (target instanceof HTMLImageElement) target.closest(".media-frame")?.classList.add(className);
  };
  document.addEventListener("error", onMedia("is-broken"), true);
  document.addEventListener("load", onMedia("is-loaded"), true);
})();
