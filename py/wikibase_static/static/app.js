// Language switch: flips data-lang on <html>; the page head hides the other language.
(function () {
  var root = document.documentElement;
  var buttons = document.querySelectorAll("[data-set-lang]");
  function show(lang) {
    root.setAttribute("data-lang", lang);
    root.setAttribute("lang", lang);
    buttons.forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-set-lang") === lang ? "true" : "false");
    });
  }
  var start = root.getAttribute("data-lang");
  var allowed = Array.prototype.map.call(buttons, function (b) { return b.getAttribute("data-set-lang"); });
  try {
    var saved = window.localStorage.getItem("wbs-lang");
    if (saved && allowed.indexOf(saved) !== -1) { start = saved; }
  } catch (e) { /* storage may be blocked */ }
  show(start);
  buttons.forEach(function (b) {
    b.addEventListener("click", function () {
      var lang = b.getAttribute("data-set-lang");
      show(lang);
      try { window.localStorage.setItem("wbs-lang", lang); } catch (e) { /* ignore */ }
    });
  });
})();
