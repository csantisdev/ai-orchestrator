(function () {
  function _apply(name) {
    if (!name || name === "dark") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.setAttribute("data-theme", name);
    }
  }

  window.setDocTheme = function (name) {
    _apply(name);
    try { localStorage.setItem("theme", name || "dark"); } catch (e) {}
    var sel = document.getElementById("docsThemeSelect");
    if (sel) sel.value = name || "dark";
  };

  // Apply saved theme before paint to avoid flash
  try {
    var saved = localStorage.getItem("theme");
    if (saved) _apply(saved);
  } catch (e) {}

  document.addEventListener("DOMContentLoaded", function () {
    var saved = "dark";
    try { saved = localStorage.getItem("theme") || "dark"; } catch (e) {}
    var sel = document.getElementById("docsThemeSelect");
    if (sel) {
      sel.value = saved;
      sel.addEventListener("change", function () {
        window.setDocTheme(this.value);
      });
    }
  });
})();
