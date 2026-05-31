// Theme handling. Two pieces:
//
//   applyTheme()  - runs in <head> before paint to set data-theme on <html>
//                   based on the stored preference, killing FOUC.
//   themeToggle() - Alpine component factory that powers the toggle button.
//
// The two share one localStorage key ("pave-theme") and one set of
// possible values ("light" | "dark" | "system").

(function () {
  const KEY = "pave-theme";
  const VALUES = ["light", "dark", "system"];

  function readPref() {
    try {
      const v = localStorage.getItem(KEY);
      return VALUES.includes(v) ? v : "system";
    } catch {
      return "system";
    }
  }

  function systemPrefersDark() {
    return (
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    );
  }

  function resolve(pref) {
    if (pref === "system") return systemPrefersDark() ? "dark" : "light";
    return pref;
  }

  function apply(pref) {
    const resolved = resolve(pref);
    document.documentElement.setAttribute("data-theme", resolved);
  }

  // Apply at load time. base.html also calls this inline before the script
  // tag finishes loading so the initial paint is correct, but re-applying
  // here is harmless and covers cached pages that swap in via HTMX boost.
  apply(readPref());

  // If the OS flips theme and the user has "system" selected, follow it.
  if (window.matchMedia) {
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", () => {
        if (readPref() === "system") apply("system");
      });
  }

  // Expose the Alpine component factory on window so the template can
  // reference it via x-data="themeToggle()". Alpine reads window scope.
  window.themeToggle = function () {
    return {
      open: false,
      preference: readPref(),
      resolved: resolve(readPref()),
      options: [
        { value: "light", label: "Light" },
        { value: "dark", label: "Dark" },
        { value: "system", label: "System" },
      ],
      init() {
        // Keep `resolved` in sync if the OS theme changes under us.
        if (window.matchMedia) {
          window
            .matchMedia("(prefers-color-scheme: dark)")
            .addEventListener("change", () => {
              if (this.preference === "system") {
                this.resolved = resolve("system");
              }
            });
        }
      },
      set(value) {
        this.preference = value;
        try {
          localStorage.setItem(KEY, value);
        } catch {
          // Storage can be unavailable in private modes; fall back to
          // in-memory only and let the click still apply the theme.
        }
        apply(value);
        this.resolved = resolve(value);
        this.open = false;
      },
    };
  };
})();
