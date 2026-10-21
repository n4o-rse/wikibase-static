// Query page (PRIMER.md, S6): editable example queries, run in the browser by rdflib under Pyodide.
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

  // The result of a query (the parsed JSON of wbs_run) as HTML: a table, or a message when it is empty.
  function resultHtml(data, config, texts) {
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

  var api = { esc: esc, format: format, fullQuery: fullQuery, iriHref: iriHref, shortIri: shortIri, cellHtml: cellHtml, resultHtml: resultHtml };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  if (typeof document === "undefined") { return; }

  // ---- the page ---------------------------------------------------------------------------------

  function readJson(id) {
    var node = document.getElementById(id);
    return node ? JSON.parse(node.textContent) : null;
  }

  function init() {
    var root = document.querySelector(".sparql");
    var config = readJson("wbs-sparql-config");
    var runner = readJson("wbs-sparql-runner");
    if (!root || !config || !runner) { return; }

    var status = document.getElementById("wbs-sparql-status");
    var booting = null;      // the promise of the one boot, so that two clicks do not start two
    var pyodide = null;

    function language() { return document.documentElement.getAttribute("data-lang") || config.default; }
    function texts() { return config.texts[language()] || config.texts[config.default]; }
    function setStatus(text, state) {
      status.textContent = text;
      status.setAttribute("data-state", state || "");
    }
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

    async function run(section) {
      var button = section.querySelector("button.run");
      var area = section.querySelector("textarea");
      var out = section.querySelector(".query-result");
      var stats = section.querySelector(".query-stats");
      button.disabled = true;
      out.innerHTML = "";
      stats.textContent = "";
      try {
        await boot();
        stats.textContent = texts().running;
        // Let the browser paint "running" before Python blocks the page.
        await new Promise(function (resolve) { setTimeout(resolve, 20); });
        var started = performance.now();
        pyodide.globals.set("wbs_query", fullQuery(config.prefixText, area.value));
        pyodide.globals.set("wbs_max", config.maxRows);
        var data = JSON.parse(pyodide.runPython("wbs_run(wbs_graph, wbs_query, wbs_max)"));
        out.innerHTML = resultHtml(data, config, texts());
        stats.textContent = format(texts().done, { s: ((performance.now() - started) / 1000).toFixed(1), n: data.triples });
      } catch (err) {
        // A mistyped query is the normal case on a page meant to be edited: show the parser's own message.
        // (a failed start has already said so in the status line)
        if (!err.isBoot) { out.innerHTML = '<pre class="error">' + esc(err.message) + "</pre>"; }
        stats.textContent = "";
      }
      button.disabled = false;
    }

    function fit(area) {
      area.style.height = "auto";
      area.style.height = area.scrollHeight + 2 + "px";
    }

    Array.prototype.forEach.call(root.querySelectorAll("section.query"), function (section) {
      var area = section.querySelector("textarea");
      var original = area.value;
      fit(area);
      area.addEventListener("input", function () { fit(area); });
      section.querySelector("button.run").addEventListener("click", function () { run(section); });
      section.querySelector("button.reset").addEventListener("click", function () {
        area.value = original;
        fit(area);
        section.querySelector(".query-result").innerHTML = "";
        section.querySelector(".query-stats").textContent = "";
      });
    });
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(function () {
        Array.prototype.forEach.call(root.querySelectorAll("textarea"), fit);
      });
    }
  }

  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", init); } else { init(); }
})();
