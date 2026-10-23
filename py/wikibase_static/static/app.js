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

// Copy the concept URI of the entity (a button with data-copy). The clipboard API needs a secure context (https or
// localhost); on a page opened from a file or an old browser a hidden textarea and execCommand do the same.
(function () {
  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(area);
      if (ok) { resolve(); } else { reject(new Error("copy failed")); }
    });
  }
  document.querySelectorAll("[data-copy-from]").forEach(function (button) {      // the rows of a source table (S7f)
    var label = button.querySelector(".copy-label");
    var done = button.querySelector(".copy-done");
    button.addEventListener("click", function () {
      var source = document.getElementById(button.getAttribute("data-copy-from"));
      if (!source) { return; }
      copy(source.textContent).then(function () {
        if (label && done) { label.hidden = true; done.hidden = false; }
        window.setTimeout(function () {
          if (label && done) { label.hidden = false; done.hidden = true; }
        }, 1500);
      }, function () { window.prompt("CSV", source.textContent); });
    });
  });
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    var label = button.querySelector(".copy-label");
    var done = button.querySelector(".copy-done");
    button.addEventListener("click", function () {
      copy(button.getAttribute("data-copy")).then(function () {
        if (label && done) { label.hidden = true; done.hidden = false; }
        window.setTimeout(function () {
          if (label && done) { label.hidden = false; done.hidden = true; }
        }, 1500);
      }, function () { window.prompt("URI", button.getAttribute("data-copy")); });
    });
  });
})();

// The tab "Source rows" is a link to a <details> element; a link to a closed <details> does not open it, so open it here.
(function () {
  function openSource() {
    var details = document.getElementById("source-rows");
    if (details && window.location.hash === "#source-rows") {
      details.open = true;
      details.scrollIntoView();
    }
  }
  openSource();
  window.addEventListener("hashchange", openSource);
})();
