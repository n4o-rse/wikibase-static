// Query pages (PRIMER.md, S6): editable example queries (sparql.html) and a free query editor with table, map and
// image views (query.html), run in the browser by rdflib under Pyodide.
//
// Nothing is loaded until somebody presses Run: then Pyodide comes from a CDN, rdflib from PyPI (through micropip)
// and the Turtle file from this site, and the query runs on the reader's machine. What is typed does not leave it.
// The Python that runs the query is the one the build ran to check every example (RUNNER_PY in sparql.py,
// handed over in #wbs-sparql-runner), so what was verified is what runs. The functions at the top are plain and
// are tested under Node; the part that touches the page starts at init().
(function () {
  "use strict";

  // ---- pure helpers -----------------------------------------------------------------------------

  // Escape once, centrally: cell values come from the data and may hold <, & or quotes.
  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // "{n} rows" with {name} replaced from vars; an unknown name stays as it is.
  function format(template, vars) {
    return String(template).replace(/\{(\w+)\}/g, function (all, name) {
      return Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : all;
    });
  }

  // The prefixes are put in front of every query, as the build did when it checked the examples.
  function fullQuery(prefixes, body) {
    return prefixes + body;
  }

  // An IRI of the Wikibase (config.entityBase + "Q1") links to the page of this site; any other http(s) IRI to itself.
  function iriHref(iri, config) {
    var base = config && config.entityBase;
    if (base && iri.indexOf(base) === 0) {
      var id = iri.slice(base.length);
      if (/^[QP][1-9][0-9]*$/.test(id)) { return id + ".html"; }
    }
    return /^https?:\/\//.test(iri) ? iri : null;
  }

  // Short form of an IRI for display: the prefix of the page when a namespace matches, else the IRI.
  function shortIri(iri, config) {
    var best = null;
    var prefixes = (config && config.prefixes) || {};
    Object.keys(prefixes).forEach(function (name) {
      var ns = prefixes[name];
      if (iri.indexOf(ns) === 0 && iri.length > ns.length && (!best || ns.length > best.ns.length)) {
        best = { name: name, ns: ns };
      }
    });
    return best ? best.name + ":" + iri.slice(best.ns.length) : iri;
  }

  // One table cell. cell is null (unbound) or [kind, text, extra] as produced by RUNNER_PY.
  function cellHtml(cell, config, texts) {
    if (cell === null || cell === undefined) { return '<td class="nil" title="' + esc(texts.unbound) + '">&mdash;</td>'; }
    var kind = cell[0], text = cell[1], extra = cell[2] || "";
    if (kind === "u") {
      var href = iriHref(text, config);
      var shown = esc(shortIri(text, config));
      var link = href ? '<a href="' + esc(href) + '"' + (href === text ? ' target="_blank" rel="noopener"' : "") + ">" + shown + "</a>" : shown;
      return '<td class="iri" title="' + esc(text) + '">' + link + "</td>";
    }
    if (kind === "b") { return '<td class="bnode">_:' + esc(text) + "</td>"; }
    var lang = extra && extra.indexOf("://") < 0 ? ' <span class="lang">@' + esc(extra) + "</span>" : "";
    var title = extra && extra.indexOf("://") >= 0 ? ' title="' + esc(extra) + '"' : "";
    return "<td" + title + ">" + esc(text) + lang + "</td>";
  }

  // ---- what a result can be shown as ---------------------------------------------------------------

  var IMAGE_EXT = /\.(jpe?g|png|gif|svg|webp|bmp|tiff?)$/i;
  var NUMBER = "(-?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?)";
  var POINT = new RegExp("^\\s*(?:<([^>]*)>\\s*)?Point\\s*\\(\\s*" + NUMBER + "\\s+" + NUMBER + "\\s*\\)\\s*$", "i");
  var EARTH = /\/Q2$/;

  // "Point(lon lat)" (as Wikibase writes coordinates) -> [lat, lon]; null for anything else, for values out of range
  // and for a point on another globe (an IRI in front of the Point that is not Earth).
  function wktPoint(text) {
    var m = POINT.exec(String(text));
    if (!m) { return null; }
    if (m[1] && !EARTH.test(m[1])) { return null; }
    var lon = parseFloat(m[2]), lat = parseFloat(m[3]);
    if (!isFinite(lat) || !isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) { return null; }
    return [lat, lon];
  }

  function isImageIri(iri) {
    var path = String(iri).split("#")[0].split("?")[0];
    try { path = decodeURIComponent(path); } catch (err) { /* keep the raw path */ }
    return /^https?:\/\//.test(iri) && IMAGE_EXT.test(path);
  }

  // Files on Commons come through Special:FilePath: as a thumbnail for the grid, in full behind the link; both over https.
  function imageUrls(iri) {
    var full = String(iri).replace(/^http:\/\/(commons\.wikimedia\.org\/)/, "https://$1");
    var thumb = /^https:\/\/commons\.wikimedia\.org\/wiki\/Special:FilePath\//.test(full) && full.indexOf("?") < 0
      ? full + "?width=360" : full;
    return { thumb: thumb, full: full };
  }

  // The part of a row that names it: its first plain literal, else its first IRI (short), else "".
  function rowLabel(row, skip, config) {
    var i, cell;
    for (i = 0; i < row.length; i++) {
      cell = row[i];
      if (cell && !skip[i] && cell[0] === "l") { return cell[1]; }
    }
    for (i = 0; i < row.length; i++) {
      cell = row[i];
      if (cell && !skip[i] && cell[0] === "u") { return shortIri(cell[1], config); }
    }
    return "";
  }

  function rowLink(row, config) {
    for (var i = 0; i < row.length; i++) {
      var cell = row[i];
      if (cell && cell[0] === "u") {
        var href = iriHref(cell[1], config);
        if (href && href.indexOf("http") !== 0) { return href; }
      }
    }
    return null;
  }

  // One marker for each row that has a coordinate: {lat, lon, label, href}.
  function extractPoints(data, config) {
    var points = [];
    (data.rows || []).forEach(function (row) {
      var skip = {}, at = null;
      row.forEach(function (cell, i) {
        if (cell && cell[0] === "l") {
          var p = wktPoint(cell[1]);
          if (p) { skip[i] = true; if (!at) { at = p; } }
        }
      });
      if (at) { points.push({ lat: at[0], lon: at[1], label: rowLabel(row, skip, config), href: rowLink(row, config) }); }
    });
    return points;
  }

  // One picture for each image IRI in the result: {thumb, full, label, href}.
  function extractImages(data, config) {
    var images = [];
    (data.rows || []).forEach(function (row) {
      var skip = {};
      row.forEach(function (cell, i) { if (cell && cell[0] === "u" && isImageIri(cell[1])) { skip[i] = true; } });
      row.forEach(function (cell, i) {
        if (skip[i]) {
          var urls = imageUrls(cell[1]);
          images.push({ thumb: urls.thumb, full: urls.full, label: rowLabel(row, skip, config), href: rowLink(row, config) });
        }
      });
    });
    return images;
  }

  function availableViews(data, config) {
    var isTable = !data.kind || data.kind === "select";
    return {
      table: true,
      map: isTable && extractPoints(data, config).length > 0,
      images: isTable && extractImages(data, config).length > 0
    };
  }

  // "#defaultView:Map" in the query (as on the Wikidata Query Service) names the view to open first.
  function parseDefaultView(query) {
    var m = /^[ \t]*#[ \t]*defaultView[ \t]*:[ \t]*(\w+)/im.exec(String(query));
    if (!m) { return null; }
    var name = m[1].toLowerCase();
    if (name === "map") { return "map"; }
    if (name === "imagegrid" || name === "images" || name === "image") { return "images"; }
    if (name === "table") { return "table"; }
    return null;
  }

  // ---- downloads ------------------------------------------------------------------------------------

  function csvField(value) {
    var text = String(value);
    return /[",\r\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }

  function cellText(cell) { return cell ? String(cell[1]) : ""; }

  // The table of a SELECT as CSV (RFC 4180, CRLF); an ASK as one column "answer".
  function toCsv(data) {
    if (data.kind === "ask") { return "answer\r\n" + (data.answer ? "true" : "false") + "\r\n"; }
    var lines = [data.cols.map(csvField).join(",")];
    data.rows.forEach(function (row) { lines.push(row.map(function (cell) { return csvField(cellText(cell)); }).join(",")); });
    return lines.join("\r\n") + "\r\n";
  }

  // The table of a SELECT in the W3C format "SPARQL 1.1 Query Results JSON"; an ASK as its boolean form.
  function toSparqlJson(data) {
    if (data.kind === "ask") { return JSON.stringify({ head: {}, boolean: !!data.answer }, null, 2); }
    var bindings = data.rows.map(function (row) {
      var binding = {};
      data.cols.forEach(function (name, i) {
        var cell = row[i];
        if (!cell) { return; }
        if (cell[0] === "u") { binding[name] = { type: "uri", value: cell[1] }; }
        else if (cell[0] === "b") { binding[name] = { type: "bnode", value: cell[1] }; }
        else {
          var term = { type: "literal", value: cell[1] };
          if (cell[2] && cell[2].indexOf("://") < 0) { term["xml:lang"] = cell[2]; }
          else if (cell[2]) { term.datatype = cell[2]; }
          binding[name] = term;
        }
      });
      return binding;
    });
    return JSON.stringify({ head: { vars: data.cols }, results: { bindings: bindings } }, null, 2);
  }

  // ---- results as HTML ------------------------------------------------------------------------------

  function tableHtml(data, config, texts) {
    if (!data.rows.length) { return '<p class="note">' + esc(texts.empty) + "</p>"; }
    var html = '<div class="table-scroll"><table class="list result"><thead><tr>';
    data.cols.forEach(function (name) { html += "<th>" + esc(name) + "</th>"; });
    html += "</tr></thead><tbody>";
    data.rows.forEach(function (row) {
      html += "<tr>" + row.map(function (cell) { return cellHtml(cell, config, texts); }).join("") + "</tr>";
    });
    html += "</tbody></table></div>";
    var note = data.total > data.rows.length
      ? format(texts.capped, { shown: data.rows.length, total: data.total })
      : format(data.total === 1 ? texts.rows_one : texts.rows_other, { n: data.total });
    return html + '<p class="note">' + esc(note) + "</p>";
  }

  // The result of a query (the parsed JSON of wbs_run) as HTML: a table, the answer of an ASK, or the triples of a CONSTRUCT.
  function resultHtml(data, config, texts) {
    if (data.kind === "ask") {
      return '<p class="answer ' + (data.answer ? "yes" : "no") + '">' + esc(data.answer ? texts.ask_true : texts.ask_false) + "</p>";
    }
    if (data.kind === "graph") {
      return '<pre class="turtle">' + esc(data.turtle) + '</pre><p class="note">' + esc(format(texts.graph_count, { n: data.count })) + "</p>";
    }
    return tableHtml(data, config, texts);
  }

  // The parser counts from the first PREFIX line that was put in front of the query; the reader sees only the query.
  function errorText(message, prefixText) {
    var lines = (String(prefixText).match(/\n/g) || []).length, chars = String(prefixText).length;
    return String(message)
      .replace(/\(at char (\d+)\)/, function (all, n) { return "(at char " + Math.max(parseInt(n, 10) - chars, 0) + ")"; })
      .replace(/\(line:(\d+)/, function (all, n) { return "(line:" + Math.max(parseInt(n, 10) - lines, 1); });
  }

  var MAX_IMAGES = 200;

  function imagesHtml(images, texts) {
    var shown = images.slice(0, MAX_IMAGES);
    var html = '<ul class="gallery">';
    shown.forEach(function (image) {
      var label = image.label ? esc(image.label) : "";
      html += "<li><a href=\"" + esc(image.full) + '" target="_blank" rel="noopener"><img loading="lazy" src="' + esc(image.thumb) +
        '" alt="' + label + '"></a>' + (label ? "<span>" + (image.href ? '<a href="' + esc(image.href) + '">' + label + "</a>" : label) + "</span>" : "") + "</li>";
    });
    html += "</ul>";
    if (images.length > shown.length) { html += '<p class="note">' + esc(format(texts.images_capped, { shown: shown.length, total: images.length })) + "</p>"; }
    return html;
  }

  var api = {
    esc: esc, format: format, fullQuery: fullQuery, iriHref: iriHref, shortIri: shortIri, cellHtml: cellHtml,
    resultHtml: resultHtml, tableHtml: tableHtml, imagesHtml: imagesHtml, wktPoint: wktPoint, isImageIri: isImageIri,
    imageUrls: imageUrls, extractPoints: extractPoints, extractImages: extractImages, availableViews: availableViews,
    parseDefaultView: parseDefaultView, errorText: errorText, toCsv: toCsv, toSparqlJson: toSparqlJson
  };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  if (typeof document === "undefined") { return; }

  // ---- the page ---------------------------------------------------------------------------------

  function readJson(id) {
    var node = document.getElementById(id);
    return node ? JSON.parse(node.textContent) : null;
  }

  // Pyodide and rdflib are started by the first query of either page; the graph is parsed once.
  function makeRuntime(config, runner, setStatus, texts) {
    var booting = null;      // the promise of the one boot, so that two clicks do not start two
    var pyodide = null;

    function loadScript(src) {
      return new Promise(function (resolve, reject) {
        var tag = document.createElement("script");
        tag.src = src;
        tag.onload = resolve;
        tag.onerror = function () { reject(new Error(src)); };
        document.head.appendChild(tag);
      });
    }

    function boot() {
      if (booting) { return booting; }
      booting = (async function () {
        var t = texts();
        setStatus(t.loading_runtime, "busy");
        try {
          await loadScript(config.pyodideUrl);
        } catch (err) {
          throw new Error(format(t.runtime_unreachable, { url: err.message }));
        }
        pyodide = await window.loadPyodide();
        setStatus(texts().loading_rdflib, "busy");
        await pyodide.loadPackage("micropip");
        pyodide.globals.set("wbs_rdflib", "rdflib==" + config.rdflibVersion);
        await pyodide.runPythonAsync("import micropip\nawait micropip.install(wbs_rdflib)");
        await pyodide.runPythonAsync(runner);
        setStatus(texts().loading_graph, "busy");
        var response;
        try {
          response = await fetch(config.graphUrl);
        } catch (err) {
          throw new Error(texts().graph_unreachable);
        }
        if (!response.ok) { throw new Error(format(texts().graph_http, { status: response.status })); }
        pyodide.globals.set("wbs_text", await response.text());
        await pyodide.runPythonAsync("wbs_graph = wbs_parse(wbs_text)");
        var triples = pyodide.runPython("len(wbs_graph)");
        setStatus(format(texts().ready, { n: triples }), "ok");
      })();
      booting.catch(function (err) {
        booting = null;                       // a second click tries again
        err.isBoot = true;
        setStatus(format(texts().start_failed, { error: err.message }), "err");
      });
      return booting;
    }

    // Runs one query (without prefixes: they are put in front) and returns the parsed answer of wbs_run.
    async function query(body) {
      await boot();
      // Let the browser paint "running" before Python blocks the page.
      await new Promise(function (resolve) { setTimeout(resolve, 20); });
      pyodide.globals.set("wbs_query", fullQuery(config.prefixText, body));
      pyodide.globals.set("wbs_max", config.maxRows);
      return JSON.parse(pyodide.runPython("wbs_run(wbs_graph, wbs_query, wbs_max)"));
    }

    return { boot: boot, query: query };
  }

  function fit(area) {
    area.style.height = "auto";
    area.style.height = area.scrollHeight + 2 + "px";
  }

  function editorHref(body) { return "query.html#q=" + encodeURIComponent(body); }

  // sparql.html: the example queries, each with its own Run.
  function initExamples(root, config, runtime, texts) {
    Array.prototype.forEach.call(root.querySelectorAll("section.query"), function (section) {
      var area = section.querySelector("textarea");
      var button = section.querySelector("button.run");
      var out = section.querySelector(".query-result");
      var stats = section.querySelector(".query-stats");
      var original = area.value;
      var toEditor = section.querySelector("a.to-editor");
      fit(area);
      area.addEventListener("input", function () { fit(area); });
      if (toEditor) { toEditor.addEventListener("click", function () { toEditor.href = editorHref(area.value); }); }
      button.addEventListener("click", async function () {
        button.disabled = true;
        out.innerHTML = "";
        stats.textContent = "";
        try {
          stats.textContent = texts().running;
          var started = performance.now();
          var data = await runtime.query(area.value);
          out.innerHTML = resultHtml(data, config, texts());
          stats.textContent = format(texts().done, { s: ((performance.now() - started) / 1000).toFixed(1), n: data.triples });
        } catch (err) {
          // A mistyped query is the normal case on a page meant to be edited: show the parser's own message.
          // (a failed start has already said so in the status line)
          if (!err.isBoot) { out.innerHTML = '<pre class="error">' + esc(errorText(err.message, config.prefixText)) + "</pre>"; }
          stats.textContent = "";
        }
        button.disabled = false;
      });
      section.querySelector("button.reset").addEventListener("click", function () {
        area.value = original;
        fit(area);
        out.innerHTML = "";
        stats.textContent = "";
      });
    });
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(function () {
        Array.prototype.forEach.call(root.querySelectorAll("textarea"), fit);
      });
    }
  }

  function download(name, type, text) {
    var url = URL.createObjectURL(new Blob([text], { type: type }));
    var link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  // query.html: one free editor, a list of examples, and the result as table, map or pictures.
  function initEditor(root, config, runtime, texts, language) {
    var $ = function (id) { return document.getElementById(id); };
    var editor = $("wbs-q-editor"), picker = $("wbs-q-examples"), run = $("wbs-q-run"), share = $("wbs-q-share");
    var stats = $("wbs-q-stats"), result = $("wbs-q-result"), tabs = $("wbs-q-views");
    var panels = { table: $("wbs-q-table"), map: $("wbs-q-map"), images: $("wbs-q-images") };
    var last = null, map = null, layer = null, drawn = null;

    function exampleTitle(example) {
      return example.title[language()] || example.title[config.default] || example.id;
    }
    function fillPicker() {
      var chosen = picker.value;
      picker.options.length = 1;
      config.examples.forEach(function (example, i) {
        var option = document.createElement("option");
        option.value = String(i);
        option.textContent = exampleTitle(example);
        picker.appendChild(option);
      });
      picker.value = chosen;
    }
    fillPicker();
    new MutationObserver(fillPicker).observe(document.documentElement, { attributes: true, attributeFilter: ["data-lang"] });

    function setView(name) {
      Object.keys(panels).forEach(function (key) { panels[key].hidden = key !== name; });
      Array.prototype.forEach.call(tabs.querySelectorAll("button"), function (button) {
        button.setAttribute("aria-selected", button.getAttribute("data-view") === name ? "true" : "false");
      });
      if (name === "map") { drawMap(); }
    }

    function drawMap() {
      if (!last || typeof L === "undefined") { return; }
      var points = extractPoints(last, config);
      if (!map) {
        L.Icon.Default.imagePath = "assets/vendor/leaflet/images/";
        map = L.map(panels.map, { scrollWheelZoom: false });
        L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 19,
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
        }).addTo(map);
        layer = L.layerGroup().addTo(map);
      }
      map.invalidateSize();
      if (drawn === last) { return; }
      drawn = last;
      layer.clearLayers();
      var bounds = [];
      points.forEach(function (p) {
        var marker = L.marker([p.lat, p.lon]).addTo(layer);
        if (p.label) { marker.bindTooltip(esc(p.label)); }
        if (p.href) { marker.bindPopup('<a href="' + esc(p.href) + '">' + esc(p.label || p.href) + "</a>"); }
        bounds.push([p.lat, p.lon]);
      });
      if (bounds.length === 1) { map.setView(bounds[0], 13); } else { map.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 }); }
    }

    function show(data, view) {
      last = data;
      drawn = null;
      var views = availableViews(data, config);
      panels.table.innerHTML = resultHtml(data, config, texts());
      panels.images.innerHTML = views.images ? imagesHtml(extractImages(data, config), texts()) : "";
      Array.prototype.forEach.call(tabs.querySelectorAll("button"), function (button) {
        button.hidden = !views[button.getAttribute("data-view")];
      });
      tabs.hidden = !(views.map || views.images);
      $("wbs-q-downloads").hidden = !(data.kind === "select" || data.kind === "ask");
      result.hidden = false;
      setView(view && views[view] ? view : "table");
    }

    async function execute() {
      run.disabled = true;
      stats.textContent = texts().running;
      result.hidden = true;
      var body = editor.value;
      try {
        var started = performance.now();
        var data = await runtime.query(body);
        show(data, parseDefaultView(body));
        stats.textContent = format(texts().done, { s: ((performance.now() - started) / 1000).toFixed(1), n: data.triples });
      } catch (err) {
        if (!err.isBoot) {
          panels.table.innerHTML = '<pre class="error">' + esc(errorText(err.message, config.prefixText)) + "</pre>";
          tabs.hidden = true;
          $("wbs-q-downloads").hidden = true;
          result.hidden = false;
          setView("table");
        }
        stats.textContent = "";
      }
      run.disabled = false;
    }

    run.addEventListener("click", execute);
    editor.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); execute(); }
    });
    picker.addEventListener("change", function () {
      var example = config.examples[parseInt(picker.value, 10)];
      if (example) { editor.value = example.sparql; }
    });
    Array.prototype.forEach.call(tabs.querySelectorAll("button"), function (button) {
      button.addEventListener("click", function () { setView(button.getAttribute("data-view")); });
    });
    $("wbs-q-csv").addEventListener("click", function () { if (last) { download("result.csv", "text/csv;charset=utf-8", toCsv(last)); } });
    $("wbs-q-json").addEventListener("click", function () {
      if (last) { download("result.json", "application/sparql-results+json;charset=utf-8", toSparqlJson(last)); }
    });
    share.addEventListener("click", function () {
      var hash = "q=" + encodeURIComponent(editor.value);
      try { history.replaceState(null, "", "#" + hash); } catch (err) { window.location.hash = hash; }
      var done = function () { stats.textContent = texts().link_copied; };
      var failed = function () { stats.textContent = texts().link_in_address_bar; };
      if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(window.location.href).then(done, failed); } else { failed(); }
    });

    // A link made by "Share" or by "Open in the query editor" carries the query in the address.
    var preset = /^#q=(.*)$/.exec(window.location.hash);
    if (preset) {
      try { editor.value = decodeURIComponent(preset[1]); } catch (err) { /* a broken link keeps the default query */ }
    }
    fit(editor);
    editor.addEventListener("input", function () { fit(editor); });
  }

  function init() {
    var root = document.querySelector(".sparql");
    var config = readJson("wbs-sparql-config");
    var runner = readJson("wbs-sparql-runner");
    if (!root || !config || !runner) { return; }
    if (typeof L !== "undefined") { L.Icon.Default.imagePath = "assets/vendor/leaflet/images/"; }

    var status = document.getElementById("wbs-sparql-status");
    function language() { return document.documentElement.getAttribute("data-lang") || config.default; }
    function texts() { return config.texts[language()] || config.texts[config.default]; }
    function setStatus(text, state) {
      status.textContent = text;
      status.setAttribute("data-state", state || "");
    }
    var runtime = makeRuntime(config, runner, setStatus, texts);
    if (document.getElementById("wbs-q-editor")) { initEditor(root, config, runtime, texts, language); } else { initExamples(root, config, runtime, texts); }
  }

  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", init); } else { init(); }
})();
