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

// Download of a data-model graphic (buttons with data-graph-download="svg" or "png" inside an element with data-graph-name).
// The SVG is the one on the page, copied with its own styles; links become absolute, so they work in the saved file.
// The PNG is drawn from it on a canvas (twice the size, white ground). Without JavaScript the buttons stay hidden.
(function () {
  var buttons = document.querySelectorAll("[data-graph-download]");
  function source(box) {
    var svg = box.querySelector("svg.model-graph");
    if (!svg) { return null; }
    var box_ = svg.viewBox.baseVal, copy = svg.cloneNode(true);
    copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    copy.setAttribute("width", box_.width);
    copy.setAttribute("height", box_.height);
    copy.removeAttribute("style");
    copy.querySelectorAll("a[href]").forEach(function (a) {
      a.setAttribute("href", new URL(a.getAttribute("href"), document.baseURI).href);
    });
    return { xml: '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(copy), width: box_.width, height: box_.height };
  }
  function save(blob, name) {
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = name;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
  }
  buttons.forEach(function (button) {
    button.hidden = false;
    button.addEventListener("click", function () {
      var box = button.closest("[data-graph-name]");
      var picture = box && source(box);
      if (!picture) { return; }
      var name = box.getAttribute("data-graph-name");
      if (button.getAttribute("data-graph-download") === "svg") {
        save(new Blob([picture.xml], { type: "image/svg+xml" }), name + ".svg");
        return;
      }
      var image = new Image();
      image.onload = function () {
        var canvas = document.createElement("canvas");
        canvas.width = picture.width * 2;
        canvas.height = picture.height * 2;
        var context = canvas.getContext("2d");
        context.fillStyle = "#fff";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        canvas.toBlob(function (blob) { if (blob) { save(blob, name + ".png"); } }, "image/png");
      };
      image.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(picture.xml);
    });
  });
})();
