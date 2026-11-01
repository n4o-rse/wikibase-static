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
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
      }).addTo(map);
    };
    var webgl = false;
    try { var canvas = document.createElement("canvas"); webgl = !!(canvas.getContext("webgl2") || canvas.getContext("webgl")); } catch (e) { webgl = false; }
    if (!webgl) { raster(); return; }
    loadLibs().then(function (ok) {
      if (!ok) { raster(); return; }
      try {
        var gl = L.maplibreGL({ style: STYLE, maxZoom: 19, attribution: CREDIT }).addTo(map);
        var inner = gl.getMaplibreMap && gl.getMaplibreMap(), loaded = false;
        if (inner) {
          inner.on("load", function () { loaded = true; });
          inner.on("error", function () { if (!loaded) { loaded = true; map.removeLayer(gl); raster(); } });   // the style could not be fetched
        }
      } catch (e) { raster(); }
    });
  };

  // Full-screen button for every map (0.24.0; also used by sparql.js through window.wbsFullscreen). It asks the browser for real
  // full screen and, where that is not allowed or not there (an old browser, an iframe), stretches the map over the page
  // (class wbs-fs). Escape or a second click returns; the map is resized either way.
  var ICON_ENTER = '<svg viewBox="0 0 16 16" width="18" height="18" aria-hidden="true" focusable="false"><path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>';
  var ICON_LEAVE = '<svg viewBox="0 0 16 16" width="18" height="18" aria-hidden="true" focusable="false"><path d="M6 2v4H2M14 6h-4V2M10 14v-4h4M2 10h4v4" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>';
  window.wbsFullscreen = function (map) {
    var el = map.getContainer();
    var Control = L.Control.extend({
      options: { position: "topleft" },
      onAdd: function () {
        var bar = L.DomUtil.create("div", "leaflet-bar leaflet-control");
        var a = L.DomUtil.create("a", "wbs-fs-button", bar);
        a.href = "#";
        a.setAttribute("role", "button");
        a.innerHTML = ICON_ENTER;
        L.DomEvent.disableClickPropagation(bar);
        L.DomEvent.on(a, "click", function (event) { L.DomEvent.preventDefault(event); toggle(); });
        L.DomEvent.on(a, "mouseover focus", label);
        label();
        function label() {
          var german = (document.documentElement.getAttribute("lang") || "").slice(0, 2) === "de";
          var text = active() ? (german ? "Vollbild beenden" : "Exit full screen") : (german ? "Vollbild" : "Full screen");
          a.title = text;
          a.setAttribute("aria-label", text);
          var want = active() ? "leave" : "enter";
          if (a.getAttribute("data-icon") !== want) {      // only on a change: replacing the icon under the pointer would lose the click
            a.setAttribute("data-icon", want);
            a.innerHTML = want === "leave" ? ICON_LEAVE : ICON_ENTER;
          }
        }
        this._label = label;
        return bar;
      }
    });
    var control = new Control();
    el._wbsMap = map;
    function active() { return document.fullscreenElement === el || el.classList.contains("wbs-fs"); }
    // In full screen the wheel zooms (it is off on the page, where it would catch the scrolling of the page).
    function refresh() {
      if (active()) { map.scrollWheelZoom.enable(); } else { map.scrollWheelZoom.disable(); }
      window.setTimeout(function () { map.invalidateSize(); if (control._label) { control._label(); } }, 60);
    }
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
    document.addEventListener("fullscreenchange", refresh);
    document.addEventListener("keydown", function (event) { if (event.key === "Escape" && el.classList.contains("wbs-fs")) { leave(); } });
    control.addTo(map);
  };
  L.Icon.Default.imagePath = "assets/vendor/leaflet/images/";
  document.querySelectorAll(".wbs-map").forEach(function (el) {
    var points, shapes = [];
    try { points = JSON.parse(el.getAttribute("data-points")); } catch (e) { return; }
    try { shapes = JSON.parse(el.getAttribute("data-shapes") || "[]"); } catch (e) { shapes = []; }
    if ((!points || !points.length) && !shapes.length) { return; }
    points = points || [];
    var map = L.map(el, { scrollWheelZoom: false });
    window.wbsFullscreen(map);
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
    if (shapeBounds && shapeBounds.isValid()) { map.fitBounds(shapeBounds, { padding: [24, 24], maxZoom: 18 }); } else if (bounds.length === 1) { map.setView(bounds[0], 13); } else { map.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 }); }
  });
})();
