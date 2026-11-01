// Maps for coordinate values: Leaflet with OpenStreetMap tiles. Only loaded on pages that have a coordinate.
(function () {
  if (typeof L === "undefined") { return; }

  // Basemap (0.24.0): the OpenFreeMap "Positron" vector style (OpenMapTiles data from OpenStreetMap), drawn by MapLibre GL, which is
  // part of the package (assets/vendor/maplibre/) and loaded on the first map of a page. Where WebGL is missing or the style cannot be
  // fetched, the classic OpenStreetMap raster tiles take its place. In dark mode the CSS inverts the base layer (style.css).
  var STYLE = "https://tiles.openfreemap.org/styles/positron";
  var CREDIT = '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> ' +
    '<a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">&copy; OpenMapTiles</a> ' +
    'Data from <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>';
  var VENDOR = "assets/vendor/maplibre/";
  var libs = null;
  function loadLibs() {
    if (libs) { return libs; }
    function add(tag, attrs) {
      return new Promise(function (resolve, reject) {
        var node = document.createElement(tag);
        Object.keys(attrs).forEach(function (key) { node.setAttribute(key, attrs[key]); });
        node.onload = resolve;
        node.onerror = function () { reject(new Error(attrs.src || attrs.href)); };
        document.head.appendChild(node);
      });
    }
    libs = add("link", { rel: "stylesheet", href: VENDOR + "maplibre-gl.css" })
      .then(function () { return add("script", { src: VENDOR + "maplibre-gl.js" }); })
      .then(function () { return add("script", { src: VENDOR + "leaflet-maplibre-gl.js" }); })
      .then(function () { return !!L.maplibreGL; }, function () { return false; });
    return libs;
  }
  window.wbsBasemap = function (map) {
    var raster = function () {
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        crossOrigin: true,                         // lets the PNG export read the tiles
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
      }).addTo(map);
    };
    var webgl = false;
    try { var canvas = document.createElement("canvas"); webgl = !!(canvas.getContext("webgl2") || canvas.getContext("webgl")); } catch (e) { webgl = false; }
    if (!webgl) { raster(); return; }
    loadLibs().then(function (ok) {
      if (!ok) { raster(); return; }
      try {
        var gl = L.maplibreGL({ style: STYLE, maxZoom: 19, attribution: CREDIT, canvasContextAttributes: { preserveDrawingBuffer: true } }).addTo(map);
        map._wbsGl = gl;                           // the PNG export copies its canvas
        var inner = gl.getMaplibreMap && gl.getMaplibreMap(), loaded = false;
        if (inner) {
          inner.on("load", function () { loaded = true; });
          inner.on("error", function () { if (!loaded) { loaded = true; map.removeLayer(gl); map._wbsGl = null; raster(); } });   // the style could not be fetched
        }
      } catch (e) { raster(); }
    });
  };

  // Controls for every map (0.24.0 full screen, 0.24.2 the whole set; also used by sparql.js through window.wbsControls): one bar under
  // the zoom buttons with full screen, back to the first view, copy coordinates, open on openstreetmap.org, save as PNG and download
  // the shown points and shapes as GeoJSON, plus a metric scale bar. The page tells the bar what is on the map: map._wbsFeatures()
  // returns {points: [{lat, lon, text, href}], shapes: [{geometry, text}]} and map._wbsHome() fits the first view.
  var SVG = function (path) { return '<svg viewBox="0 0 16 16" width="18" height="18" aria-hidden="true" focusable="false"><path d="' + path + '" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'; };
  var ICON_ENTER = SVG("M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4");
  var ICON_LEAVE = SVG("M6 2v4H2M14 6h-4V2M10 14v-4h4M2 10h4v4");
  var ICON_HOME = SVG("M1.5 8 8 2.5 14.5 8M3.5 7v6.5H7V10h2v3.5h3.5V7");
  var ICON_PICK = SVG("M8 1.5v3M8 11.5v3M1.5 8h3M11.5 8h3M8 6.6a1.4 1.4 0 1 1 0 2.8 1.4 1.4 0 0 1 0-2.8");
  var ICON_OSM = SVG("M9 2h5v5M14 2 7.5 8.5M12 9.5V14H2.5V4.5H7");
  var ICON_PNG = SVG("M1.5 5.2h13v8.3h-13zM5.2 5.2 6.3 3h3.4l1.1 2.2M8 7.2a2.3 2.3 0 1 1 0 4.6 2.3 2.3 0 0 1 0-4.6");
  var ICON_GEOJSON = SVG("M8 2v8M4.5 6.8 8 10.3l3.5-3.5M2.5 13.5h11");
  var TEXTS = {
    en: { enter: "Full screen", leave: "Exit full screen", home: "Back to the first view", pick: "Copy coordinates (click the map)", osm: "Open on openstreetmap.org",
          png: "Save as PNG", geojson: "Download as GeoJSON", copied: "Copied: ", failed: "Not copied: " },
    de: { enter: "Vollbild", leave: "Vollbild beenden", home: "Zurück zur ersten Ansicht", pick: "Koordinaten kopieren (Klick auf die Karte)", osm: "Auf openstreetmap.org öffnen",
          png: "Als PNG speichern", geojson: "Als GeoJSON herunterladen", copied: "Kopiert: ", failed: "Nicht kopiert: " }
  };
  function texts() { return (document.documentElement.getAttribute("lang") || "").slice(0, 2) === "de" ? TEXTS.de : TEXTS.en; }
  function fileStem() {
    var stem = (location.pathname.split("/").pop() || "index").replace(/\.html?$/i, "") || "index";
    return "map-" + stem + "-" + new Date().toISOString().slice(0, 10);
  }
  function save(blob, name) {
    var url = URL.createObjectURL(blob), a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    window.setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  }
  function absolute(href) { try { return new URL(href, location.href).href; } catch (e) { return href; } }
  function features(map) {
    var got = map._wbsFeatures ? map._wbsFeatures() : null;
    return { points: (got && got.points) || [], shapes: (got && got.shapes) || [] };
  }
  function geojson(map) {
    var f = features(map), out = [];
    f.points.forEach(function (p) {
      var props = { label: p.text || p.label || "" };
      if (p.href) { props.url = absolute(p.href); }
      out.push({ type: "Feature", properties: props, geometry: { type: "Point", coordinates: [p.lon, p.lat] } });
    });
    f.shapes.forEach(function (s) { out.push({ type: "Feature", properties: { label: s.text || "" }, geometry: s.geometry }); });
    return { type: "FeatureCollection", features: out };
  }
  // PNG: the basemap is copied off the MapLibre canvas (it keeps its buffer, see wbsBasemap) or drawn from the raster tiles; markers and
  // shapes are drawn on top from the data, and the credit of the basemap is part of the picture (the licences ask for it).
  function drawGeometry(ctx, g, pt) {
    if (!g) { return; }
    function ring(coords, close) { coords.forEach(function (c, i) { var p = pt(c[1], c[0]); if (i) { ctx.lineTo(p.x, p.y); } else { ctx.moveTo(p.x, p.y); } }); if (close) { ctx.closePath(); } }
    if (g.type === "GeometryCollection") { (g.geometries || []).forEach(function (x) { drawGeometry(ctx, x, pt); }); return; }
    var polygons = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
    var lines = g.type === "LineString" ? [g.coordinates] : g.type === "MultiLineString" ? g.coordinates : [];
    if (polygons.length) { ctx.beginPath(); polygons.forEach(function (poly) { poly.forEach(function (r) { ring(r, true); }); }); ctx.fill("evenodd"); ctx.stroke(); }
    if (lines.length) { ctx.beginPath(); lines.forEach(function (l) { ring(l, false); }); ctx.stroke(); }
  }
  function drawPin(ctx, x, y) {
    var cy = y - 27, r = 11, a = 24.1 * Math.PI / 180;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + r * Math.cos(a), cy + r * Math.sin(a));
    ctx.arc(x, cy, r, a, Math.PI - a, true);
    ctx.closePath();
    ctx.fillStyle = "#2a81cb"; ctx.fill();
    ctx.lineWidth = 1.5; ctx.strokeStyle = "#1c5f99"; ctx.stroke();
    ctx.beginPath(); ctx.arc(x, cy, 4, 0, Math.PI * 2); ctx.fillStyle = "#ffffff"; ctx.fill();
  }
  function settled(gl, ms) {
    return new Promise(function (resolve) {
      if (gl.loaded()) { resolve(true); return; }
      var timer = window.setTimeout(function () { gl.off("idle", done); resolve(false); }, ms);
      function done() { window.clearTimeout(timer); resolve(true); }
      gl.once("idle", done);
    });
  }
  function exportPng(map) {
    var el = map.getContainer(), rect = el.getBoundingClientRect(), scale = 2;
    var canvas = document.createElement("canvas");
    canvas.width = Math.round(rect.width * scale);
    canvas.height = Math.round(rect.height * scale);
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = "#e8e6df";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    var layer = map._wbsGl, gl = layer && layer.getMaplibreMap && layer.getMaplibreMap(), complete = true, credit;
    var basemap;
    if (gl) {
      credit = "OpenFreeMap © OpenMapTiles Data from OpenStreetMap";
      basemap = settled(gl, 8000).then(function (ok) {
        complete = ok;
        var src = gl.getCanvas(), box = layer.getContainer().getBoundingClientRect(), k = src.width / box.width;
        ctx.drawImage(src, (rect.left - box.left) * k, (rect.top - box.top) * k, rect.width * k, rect.height * k, 0, 0, canvas.width, canvas.height);
      });
    } else {
      credit = "© OpenStreetMap contributors";
      basemap = Promise.resolve().then(function () {
        Array.prototype.forEach.call(el.querySelectorAll(".leaflet-tile-pane img.leaflet-tile-loaded"), function (img) {
          var r = img.getBoundingClientRect();
          try { ctx.drawImage(img, (r.left - rect.left) * scale, (r.top - rect.top) * scale, r.width * scale, r.height * scale); } catch (e) { complete = false; }
        });
      });
    }
    return basemap.catch(function () { complete = false; }).then(function () {
      var f = features(map), pt = function (lat, lon) { return map.latLngToContainerPoint(L.latLng(lat, lon)); };
      ctx.save();
      ctx.scale(scale, scale);
      ctx.lineWidth = 3; ctx.strokeStyle = "#c0392b"; ctx.fillStyle = "rgba(192,57,43,0.15)"; ctx.lineJoin = "round";
      f.shapes.forEach(function (s) { drawGeometry(ctx, s.geometry, pt); });
      f.points.forEach(function (p) { var q = pt(p.lat, p.lon); drawPin(ctx, q.x, q.y); });
      ctx.font = "11px sans-serif";
      var text = credit + (complete ? "" : " · basemap incomplete"), w = ctx.measureText(text).width;
      ctx.fillStyle = "rgba(255,255,255,0.85)";
      ctx.fillRect(rect.width - w - 12, rect.height - 18, w + 12, 18);
      ctx.fillStyle = "#333333";
      ctx.fillText(text, rect.width - w - 6, rect.height - 5);
      ctx.restore();
      return new Promise(function (resolve) { canvas.toBlob(function (blob) { if (blob) { save(blob, fileStem() + ".png"); } resolve(); }, "image/png"); });
    });
  }
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) { return navigator.clipboard.writeText(text); }
    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = text; area.style.position = "fixed"; area.style.opacity = "0";
      document.body.appendChild(area); area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      area.remove();
      if (ok) { resolve(); } else { reject(new Error("copy")); }
    });
  }
  window.wbsControls = function (map) {
    var el = map.getContainer(), buttons = {}, readout = null, flashTimer = null;
    var Bar = L.Control.extend({
      options: { position: "topleft" },
      onAdd: function () {
        var bar = L.DomUtil.create("div", "leaflet-bar leaflet-control");
        function add(name, icon, handler) {
          var a = L.DomUtil.create("a", "wbs-btn wbs-btn-" + name, bar);
          a.href = "#";
          a.setAttribute("role", "button");
          a.innerHTML = icon;
          L.DomEvent.on(a, "click", function (event) { L.DomEvent.preventDefault(event); handler(); });
          buttons[name] = a;
          return a;
        }
        add("fullscreen", ICON_ENTER, toggle).className += " wbs-fs-button";
        add("home", ICON_HOME, function () { if (map._wbsHome) { map._wbsHome(); } });
        add("pick", ICON_PICK, togglePick);
        add("osm", ICON_OSM, function () {
          var c = map.getCenter();
          window.open("https://www.openstreetmap.org/#map=" + map.getZoom() + "/" + c.lat.toFixed(5) + "/" + c.lng.toFixed(5), "_blank", "noopener");
        });
        add("png", ICON_PNG, function () { buttons.png.classList.add("busy"); exportPng(map).then(done, done); function done() { buttons.png.classList.remove("busy"); } });
        add("geojson", ICON_GEOJSON, function () { save(new Blob([JSON.stringify(geojson(map), null, 1)], { type: "application/geo+json" }), fileStem() + ".geojson"); });
        L.DomEvent.disableClickPropagation(bar);
        L.DomEvent.on(bar, "mouseover focusin", labels);
        labels();
        return bar;
      }
    });
    var Readout = L.Control.extend({
      options: { position: "topright" },
      onAdd: function () {
        readout = L.DomUtil.create("div", "wbs-readout leaflet-control");
        readout.hidden = true;
        return readout;
      }
    });
    function active() { return document.fullscreenElement === el || el.classList.contains("wbs-fs"); }
    function labels() {
      var t = texts();
      Object.keys(buttons).forEach(function (name) {
        var text = name === "fullscreen" ? (active() ? t.leave : t.enter) : t[name];
        buttons[name].setAttribute("data-tip", text);          // shown at once by the CSS, a title would wait a second
        buttons[name].setAttribute("aria-label", text);
      });
      Array.prototype.forEach.call(legend.querySelectorAll("[data-key]"), function (node) { node.textContent = t[node.getAttribute("data-key")]; });
      var want = active() ? "leave" : "enter", a = buttons.fullscreen;
      if (a && a.getAttribute("data-icon") !== want) {      // only on a change: replacing the icon under the pointer would lose the click
        a.setAttribute("data-icon", want);
        a.innerHTML = want === "leave" ? ICON_LEAVE : ICON_ENTER;
      }
    }
    function refresh() { window.setTimeout(function () { map.invalidateSize(); labels(); }, 60); }
    function enter() {
      if (el.requestFullscreen) {
        var request = el.requestFullscreen();
        if (request && request.then) { request.then(refresh, function () { el.classList.add("wbs-fs"); refresh(); }); }
      } else { el.classList.add("wbs-fs"); refresh(); }
    }
    function leave() {
      if (document.fullscreenElement === el) { document.exitFullscreen(); }
      el.classList.remove("wbs-fs");
      refresh();
    }
    function toggle() { if (active()) { leave(); } else { enter(); } }
    // Copy coordinates: while the button is on, the pointer shows lat, lon and a click copies them.
    function show(text) { readout.textContent = text; readout.hidden = false; }
    function format(latlng) { return latlng.lat.toFixed(5) + ", " + latlng.lng.toFixed(5); }
    function onMove(event) { if (!flashTimer) { show(format(event.latlng)); } }
    function onClick(event) {
      var text = format(event.latlng), t = texts();
      copyText(text).then(function () { flash(t.copied + text); }, function () { flash(t.failed + text); });
    }
    function flash(text) {
      show(text);
      window.clearTimeout(flashTimer);
      flashTimer = window.setTimeout(function () { flashTimer = null; if (el.classList.contains("wbs-pick")) { readout.hidden = true; } }, 1800);
    }
    function togglePick() {
      var on = !el.classList.contains("wbs-pick");
      el.classList.toggle("wbs-pick", on);
      buttons.pick.classList.toggle("on", on);
      buttons.pick.setAttribute("aria-pressed", on ? "true" : "false");
      if (on) { map.on("mousemove", onMove); map.on("click", onClick); } else { map.off("mousemove", onMove); map.off("click", onClick); readout.hidden = true; }
    }
    el._wbsMap = map;
    // The legend under the map says what each button does (the same words as the tooltips).
    var legend = document.createElement("ul");
    legend.className = "wbs-legend";
    [["enter", ICON_ENTER], ["home", ICON_HOME], ["pick", ICON_PICK], ["osm", ICON_OSM], ["png", ICON_PNG], ["geojson", ICON_GEOJSON]].forEach(function (item) {
      var li = document.createElement("li");
      li.innerHTML = '<span class="wbs-legend-icon">' + item[1] + '</span><span data-key="' + item[0] + '"></span>';
      legend.appendChild(li);
    });
    if (el.parentNode) { el.parentNode.insertBefore(legend, el.nextSibling); }
    new Bar().addTo(map);
    new Readout().addTo(map);
    L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);
    document.addEventListener("fullscreenchange", refresh);
    document.addEventListener("keydown", function (event) { if (event.key === "Escape" && el.classList.contains("wbs-fs")) { leave(); } });
  };
  window.wbsFullscreen = window.wbsControls;               // the name of 0.24.0 to 0.24.1
  L.Icon.Default.imagePath = "assets/vendor/leaflet/images/";
  document.querySelectorAll(".wbs-map").forEach(function (el) {
    var points, shapes = [];
    try { points = JSON.parse(el.getAttribute("data-points")); } catch (e) { return; }
    try { shapes = JSON.parse(el.getAttribute("data-shapes") || "[]"); } catch (e) { shapes = []; }
    if ((!points || !points.length) && !shapes.length) { return; }
    points = points || [];
    var map = L.map(el);
    map._wbsFeatures = function () { return { points: points, shapes: shapes }; };
    window.wbsControls(map);
    window.wbsBasemap(map);
    var bounds = [];
    points.forEach(function (p) {
      var marker = L.marker([p.lat, p.lon]).addTo(map).bindTooltip(p.text);
      if (p.href) {
        var link = document.createElement("a");
        link.href = p.href;
        link.textContent = p.text;
        marker.bindPopup(link);
      }
      bounds.push([p.lat, p.lon]);
    });
    var shapeBounds = null;
    shapes.forEach(function (s) {
      var layer = L.geoJSON(s.geometry, { style: { color: "#c0392b", weight: 3, fillOpacity: 0.15 } }).addTo(map).bindTooltip(s.text);
      shapeBounds = shapeBounds ? shapeBounds.extend(layer.getBounds()) : layer.getBounds();
    });
    map._wbsHome = function () {
      if (shapeBounds && shapeBounds.isValid()) { map.fitBounds(shapeBounds, { padding: [24, 24], maxZoom: 18 }); } else if (bounds.length === 1) { map.setView(bounds[0], 13); } else { map.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 }); }
    };
    map._wbsHome();
  });
})();
