// Search box with autocomplete (PRIMER.md, S5).
//
// The index (assets/search-index.js, made by `python main.py search`) is loaded the first time the box is
// used. Matching runs in the browser, on labels, aliases and ids; descriptions are shown but not searched
// (somebody typing a name rarely wants a hit that only a description contains). The matching code is a set of plain functions at the top
// so that the tests can run it under Node; the part that touches the page starts at init().
(function () {
  "use strict";

  var MAX_RESULTS = 10;

  // ---- matching ---------------------------------------------------------------------------------

  // The combining diacritical marks (U+0300 to U+036F) that NFD splits accents into. Built from code points so that
  // the source holds no invisible characters.
  var COMBINING_MARKS = new RegExp("[" + String.fromCharCode(0x300) + "-" + String.fromCharCode(0x36f) + "]", "g");

  // Lower case, no accents: "Über" is found by "uber", "Éire" by "eire". Compared as text, never as HTML.
  function normalise(text) {
    return String(text).normalize("NFD").replace(COMBINING_MARKS, "").toLowerCase();
  }

  function wordsOf(norm) {
    return norm.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  }

  // One record per entity: its id and every string it can be found by, normalised once.
  // kind 0 = a label (in any language), kind 1 = an alias.
  function prepare(index) {
    return (index.entities || []).map(function (entry, position) {
      var terms = [];
      var seen = {};
      function add(text, kind) {
        if (!text) { return; }
        var norm = normalise(text);
        var key = kind + "|" + norm;
        if (seen[key]) { return; }
        seen[key] = true;
        terms.push({ text: text, norm: norm, words: wordsOf(norm), kind: kind });
      }
      var shown = entry.l || {};
      Object.keys(shown).sort().forEach(function (lang) { add(shown[lang], 0); });
      (entry.x || []).forEach(function (text) { add(text, 0); });
      (entry.a || []).forEach(function (text) { add(text, 1); });
      return { entry: entry, position: position, idn: entry.id.toLowerCase(), terms: terms };
    });
  }

  // How well one string matches the query; lower is better, -1 for no match.
  //   type 0: the whole string        1: starts with the query
  //   type 2: every query word starts a word of the string (order does not matter)
  //   type 3: the query occurs inside the string (three characters or more)
  // Labels rank ahead of aliases at every type.
  var BY_TYPE = { 0: [1, 2], 1: [3, 4], 2: [6, 7], 3: [8, 9] };
  var ID_EXACT = 0;
  var ID_PREFIX = 5;

  function termType(term, q, tokens) {
    if (term.norm === q) { return 0; }
    if (term.norm.indexOf(q) === 0) { return 1; }
    if (tokens.length && tokens.every(function (t) {
      return term.words.some(function (w) { return w.indexOf(t) === 0; });
    })) { return 2; }
    if (q.length >= 3 && term.norm.indexOf(q) !== -1) { return 3; }
    return -1;
  }

  function labelFor(entry, lang, defaultLang) {
    var l = entry.l || {};
    return l[lang] || l[defaultLang] || entry.id;
  }

  function descriptionFor(entry, lang, defaultLang) {
    var d = entry.d || {};
    return d[lang] || d[defaultLang] || "";
  }

  // The best matches for a query: [{entry, score, via}], best first, at most MAX_RESULTS.
  // `via` is the string that matched when it is not the label shown (an alias, a label in another language).
  function search(records, query, lang, defaultLang) {
    var q = normalise(query).replace(/\s+/g, " ").trim();
    var tokens = wordsOf(q);
    if (!q || !tokens.length) { return []; }
    var collator;
    try {
      collator = new Intl.Collator(lang || undefined, { numeric: true, sensitivity: "base" });
    } catch (e) {            // a language code the browser does not know
      collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
    }
    var hits = [];
    records.forEach(function (record) {
      var score = -1;
      var via = null;
      if (record.idn === q) {
        score = ID_EXACT;
      } else if (q.length >= 2 && record.idn.indexOf(q) === 0) {
        score = ID_PREFIX;
      }
      var shownLabel = normalise(labelFor(record.entry, lang, defaultLang));
      record.terms.forEach(function (term) {
        var type = termType(term, q, tokens);
        if (type < 0) { return; }
        var value = BY_TYPE[type][term.kind];
        if (score === -1 || value < score) {
          score = value;
          via = term.norm === shownLabel ? null : term.text;
        }
      });
      if (score !== -1) {
        hits.push({ entry: record.entry, position: record.position, score: score, via: via,
                    sortLabel: labelFor(record.entry, lang, defaultLang) });
      }
    });
    hits.sort(function (a, b) {
      if (a.score !== b.score) { return a.score - b.score; }
      // Hits that only share the start of their id (q2: Q2, Q20, Q21 ...) stay in id order; all others by label.
      var byLabel = a.score === ID_PREFIX ? 0 : collator.compare(a.sortLabel, b.sortLabel);
      return byLabel || (a.position - b.position);
    });
    return hits.slice(0, MAX_RESULTS).map(function (hit) {
      return { entry: hit.entry, score: hit.score, via: hit.via };
    });
  }

  // ---- the box ----------------------------------------------------------------------------------

  function init() {
    var form = document.querySelector("form.search");
    if (!form) { return; }
    var input = form.querySelector("input");
    var list = form.querySelector(".search-results");
    var root = document.documentElement;
    var defaultLang = form.getAttribute("data-default") || root.getAttribute("lang") || "en";
    var texts = {};
    try { texts = JSON.parse(form.getAttribute("data-text") || "{}"); } catch (e) { /* keep empty */ }

    var state = "idle";       // idle -> loading -> ready | error
    var records = [];
    var current = [];         // the results on show
    var active = -1;          // the highlighted result, -1 for none

    function lang() { return root.getAttribute("data-lang") || defaultLang; }
    function text(key) {
      var set = texts[lang()] || texts[defaultLang] || {};
      return set[key] || "";
    }

    function close() {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      active = -1;
    }

    function open() {
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }

    function setActive(position) {
      var options = list.querySelectorAll("[role=option]");
      options.forEach(function (option, i) {
        option.setAttribute("aria-selected", i === position ? "true" : "false");
      });
      active = position;
      if (position >= 0 && options[position]) {
        input.setAttribute("aria-activedescendant", options[position].id);
        if (options[position].scrollIntoView) { options[position].scrollIntoView({ block: "nearest" }); }
      } else {
        input.removeAttribute("aria-activedescendant");
      }
    }

    function message(key) {
      list.textContent = "";
      var li = document.createElement("li");
      li.className = "search-message";
      li.setAttribute("role", "presentation");
      li.textContent = text(key);
      list.appendChild(li);
      current = [];
      open();
    }

    function show(results) {
      list.textContent = "";
      current = results;
      results.forEach(function (hit, i) {
        var li = document.createElement("li");
        li.id = "wbs-search-option-" + i;
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", "false");
        var link = document.createElement("a");
        link.href = hit.entry.id + ".html";
        link.tabIndex = -1;
        var label = document.createElement("span");
        label.className = "sr-label";
        label.textContent = labelFor(hit.entry, lang(), defaultLang);
        var id = document.createElement("span");
        id.className = "sr-id";
        id.textContent = " (" + hit.entry.id + ")";
        link.appendChild(label);
        link.appendChild(id);
        if (hit.via) {
          var via = document.createElement("span");
          via.className = "sr-via";
          via.textContent = " " + hit.via;
          link.appendChild(via);
        }
        var description = descriptionFor(hit.entry, lang(), defaultLang);
        if (description) {
          var line = document.createElement("span");
          line.className = "sr-desc";
          line.textContent = description;
          link.appendChild(line);
        }
        li.appendChild(link);
        list.appendChild(li);
      });
      active = -1;
      input.removeAttribute("aria-activedescendant");
      open();
    }

    function update() {
      var query = input.value;
      if (!query.trim()) { close(); return; }
      if (state === "error") { message("error"); return; }
      if (state !== "ready") { return; }    // update() runs again when the index has arrived
      var results = search(records, query, lang(), defaultLang);
      if (results.length) { show(results); } else { message("none"); }
    }

    function load() {
      if (state !== "idle") { return; }
      state = "loading";
      var script = document.createElement("script");
      script.src = form.getAttribute("data-index");
      script.onload = function () {
        var index = window.WBS_SEARCH_INDEX;
        if (index && index.entities) {
          records = prepare(index);
          state = "ready";
        } else {
          state = "error";
        }
        update();
      };
      script.onerror = function () { state = "error"; update(); };
      document.head.appendChild(script);
    }

    function go(hit) {
      if (hit) { window.location.href = hit.entry.id + ".html"; }
    }

    function translate() {
      var placeholder = text("placeholder");
      input.setAttribute("placeholder", placeholder);
      input.setAttribute("aria-label", placeholder);
      list.setAttribute("aria-label", placeholder);
    }

    input.addEventListener("focus", function () { load(); update(); });
    input.addEventListener("input", function () { load(); update(); });
    input.addEventListener("blur", close);
    input.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        if (!current.length) { return; }
        event.preventDefault();
        if (list.hidden) { open(); }
        var step = event.key === "ArrowDown" ? 1 : -1;
        var next = active + step;
        if (next < -1) { next = current.length - 1; }
        if (next >= current.length) { next = -1; }
        setActive(next);
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (current.length) { go(current[active >= 0 ? active : 0]); }
      } else if (event.key === "Escape") {
        if (!list.hidden) { close(); } else { input.value = ""; }
      }
    });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (current.length) { go(current[active >= 0 ? active : 0]); }
    });
    // A press on a result must not take the focus from the input (which would close the list before the click).
    list.addEventListener("mousedown", function (event) { event.preventDefault(); });

    // The language switch (app.js) sets data-lang on <html>; follow it.
    if (window.MutationObserver) {
      new MutationObserver(function () { translate(); if (!list.hidden) { update(); } })
        .observe(root, { attributes: true, attributeFilter: ["data-lang"] });
    }
    translate();
    form.hidden = false;     // without this script the form stays hidden: a box that cannot work is not shown
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { normalise: normalise, prepare: prepare, search: search, labelFor: labelFor, MAX_RESULTS: MAX_RESULTS };
  } else if (typeof document !== "undefined") {
    if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", init); } else { init(); }
  }
})();
