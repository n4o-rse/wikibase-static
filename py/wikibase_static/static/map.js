// Maps for coordinate values: Leaflet with OpenStreetMap tiles. Only loaded on pages that have a coordinate.
(function () {
  if (typeof L === "undefined") { return; }
  L.Icon.Default.imagePath = "assets/vendor/leaflet/images/";
  document.querySelectorAll(".wbs-map").forEach(function (el) {
    var points, shapes = [];
    try { points = JSON.parse(el.getAttribute("data-points")); } catch (e) { return; }
    try { shapes = JSON.parse(el.getAttribute("data-shapes") || "[]"); } catch (e) { shapes = []; }
    if ((!points || !points.length) && !shapes.length) { return; }
    points = points || [];
    var map = L.map(el, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
    }).addTo(map);
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
