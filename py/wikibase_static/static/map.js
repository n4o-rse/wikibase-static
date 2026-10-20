// Maps for coordinate values: Leaflet with OpenStreetMap tiles. Only loaded on pages that have a coordinate.
(function () {
  if (typeof L === "undefined") { return; }
  L.Icon.Default.imagePath = "assets/vendor/leaflet/images/";
  document.querySelectorAll(".wbs-map").forEach(function (el) {
    var points;
    try { points = JSON.parse(el.getAttribute("data-points")); } catch (e) { return; }
    if (!points || !points.length) { return; }
    var map = L.map(el, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
    }).addTo(map);
    var bounds = [];
    points.forEach(function (p) {
      L.marker([p.lat, p.lon]).addTo(map).bindTooltip(p.text);
      bounds.push([p.lat, p.lon]);
    });
    if (bounds.length === 1) { map.setView(bounds[0], 13); } else { map.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 }); }
  });
})();
