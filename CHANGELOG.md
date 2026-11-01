# Changelog

Every version is a tag `vX.Y.Z` on the commit that raised `__version__` (`tools/tag_versions.py` makes the missing tags;
`0.1.0` is the last commit before 0.2.0). The newest version is on top. The work plan with the findings behind each version is `PRIMER.md`.

## 0.24.2
- Full-screen button: the box was 40 px high with a gap on top and the icon sat off-centre (the margin of the icon collapsed out of the
  link); the link is now a flex box, so the button is 30 x 30 px like the zoom buttons and the icon is centred.
- The mouse wheel zooms every map all the time (before: only in full screen), also the result map of the query page.
- One bar of map controls under the zoom buttons (`window.wbsControls`; `wbsFullscreen` stays as an alias): full screen, back to the first
  view, copy coordinates (switch on, move the pointer, click the map), open the view on openstreetmap.org, save the map as PNG and
  download the shown points and shapes as GeoJSON. Plus a metric scale bar.
- Every button has a tooltip that shows at once, and a legend under each map names the buttons with their icons (English and German).
- PNG: the basemap is copied off the MapLibre canvas (it is created with `preserveDrawingBuffer`) or drawn from the raster tiles
  (`crossOrigin`), markers and shapes are drawn on top, and the credit of the basemap is part of the picture. The picture is always light,
  also in dark mode. Idea and method from `LinkedOpenOgham/tei--epidoc-crosswalk`.

## 0.24.1
- The light mode is the default and the system setting is no longer consulted. The button in the tab row switches between light and dark
  (two states instead of three) and remembers the choice (`wbs-theme`); the `prefers-color-scheme` rules are gone.
- Full-screen button: it shows two arrows pointing in while the map is full screen (before: the same icon), is drawn like the zoom buttons
  and a little larger, and the mouse wheel zooms the map in full screen (it stays off on the page, so that it does not catch the scrolling).

## 0.24.0
- Design: all pages use the BeaverBridge palette of `beaverbridge-registry` (plum, wood brown, coral, info blue) as CSS tokens in a
  light and a dark mode. A button in the tab row switches between them and remembers the choice (`localStorage` key `wbs-theme`); a script in the head sets it before the first paint. No fixed colour is left
  in the rules (test).
- `site.yaml` `colour` is optional: left out, the plum of the palette is the accent; set, it is used in light mode and mixed with white
  in dark mode. `DEFAULT_COLOUR` is now `#8E3A63`.
- Logo with a white ground sits on a light tile in dark mode; the data-model graphics keep their colours on a light panel.
- Maps: a full-screen button on every Leaflet map (also the result map of the query page), taller maps (28 rem on entity and overview
  pages, 40 rem on the query page, at most 75 and 80 % of the window).
- Maps: the basemap of `beaverbridge-registry`, OpenFreeMap "Positron" (vector tiles, OpenStreetMap data), drawn by MapLibre GL
  5.24.0 with maplibre-gl-leaflet 0.1.4. Both ship in `static/vendor/maplibre/` and load on the first map of a page; without WebGL
  or without the style the OpenStreetMap raster tiles are used. In dark mode the base layer is inverted by CSS.
- Tests: 654 in the repository (3 more).

## 0.23.0
- `import-osm`: German label and description (`label_de`, `description_de`) instead of "No label defined".
- Labels from a Commons file title are cleaned (underscores and CamelCase to spaces, `.jpg` and ` - geograph.org.uk - 123` removed);
  without a name or file title the inscription is used.
- Descriptions say what the item is and where it comes from, in English and German, with the inscription quoted ("Milestone,
  inscription "P.O Dublin 8 Howth 1" (OpenStreetMap node 6666122939)").
- Tests: 651 in the repository (2 more).

## 0.22.0
- `import-osm`: ways and relations become items. The shape is built from the stored histories of the member nodes (`data/raw/osm/members/`,
  fetched by the network part, `--member-limit`, `--members-dir`, `--element way/ID`), one WKT entry each time it changed.
- New modules `wkt.py` and `osm_geom.py` (ring assembly for multipolygons and boundaries).
- `site.yaml` `wkt_property`: the entity page draws the last shape on its map, the RDF export types the item `geo:Feature` and each
  entry `geo:Geometry` with `geo:asWKT` (GeoSPARQL), the last valid one as `geo:hasDefaultGeometry`.
- Tests: 649 in the repository (22 more).

## 0.21.0
- `import-osm` with the network: sends the Overpass query of a selection once, fetches `history.json` of the OSM API only for new or
  changed elements, stores every answer byte for byte (`data/raw/osm/`). `--probe`, `--refresh`, `--offline`.

## 0.20.0
- New verb `import-osm` (offline): one item per OSM element, one statement per version with changeset, user and uid, an entry marker for
  each run of versions that meet a tag condition, the position as coordinate and as WKT history. Roles are mapped by
  `data/csv/mapping/osm-properties.csv`. `crm:E25` is known to the CRM overlay.

## 0.19.0
- `site.yaml` `counterpart`: a link on every page and `owl:sameAs` in the RDF to the same entity in a real Wikibase; the table of the
  ids is offered as a CSV download.

## 0.18.3
- `site.yaml` `data_as_of` for entities that carry no modification time; long entity names in the statement graph wrap to two lines;
  in a prefix family the dataset IRI of an entity is the file's IRI with `#dataset`.

## 0.18.2
- SVG and PNG download under each data-model graphic.

## 0.18.1
- Classes with the same instances share one card in the data-model graphic.

## 0.18.0
- `site.yaml` `rdf_prefix`: an own prefix family (`chb:`, `chbt:`, ...) instead of the Wikibase names `wd:`, `wdt:`; the dataset IRI of an
  entity points at its Turtle file.
- Data-model graphics: the statement graph per entity and the class cards on the start page, drawn from the data.

## 0.17.0
- Class hierarchy on the overview and on class pages.

## 0.16.0
- Tab "Source rows" on the entity pages of CSV sites: the CSV lines of the page as text, with a copy button.

## 0.15.0
- `apply-qs`: changes the CSV tables with a QuickStatements file.

## 0.14.0
- `merge --suggest`: suggestions for duplicate items.

## 0.13.0
- Merging items: `merges.csv`, forwarding pages, `owl:sameAs`, verb `merge`.

## 0.12.0
- Seed column `instance_of`: every Wikidata seed can be made an item of a chosen class.

## 0.11.1
- `import-wikidata` sends no `maxlag` to Wikidata.

## 0.11.0
- New verb `import-wikidata`: Wikidata seeds into the CSV tables. Properties and item values go through the P4 twins; targets without a
  twin become stubs. Every statement carries the Wikidata page and the date of the revision.

## 0.10.0
- Overview page (items grouped by class, one map per class) and separate lists of items and properties.

## 0.9.1
- The default `references` query runs in 1.4 s instead of 22 s on 37 399 triples (two groups instead of three).

## 0.9.0
- New verb `import-open-archaeo`: a stratified part of the open-archaeo software list into the CSV tables, driven by a mapping and a
  vocabulary table; a reimport keeps rows written by hand.

## 0.8.0
- `data/dcat-crm.csv` ties the DCAT classes of the export to the CIDOC CRM; `subclass of` and `instance of` are also written as
  `rdfs:subClassOf` and `rdf:type`. New verb `check-crm` validates `dist/*.ttl` with SHACL.

## 0.7.0
- CIDOC CRM overlay: `data/crm.csv` ties classes to CRM families (inherited along `subclass of` and `instance of`); the export writes
  the chain up to the first `crm:` class, the entity pages show the class.

## 0.6.4
- The kernel properties get their Wikidata twins (P4: P279, P31, P1647, P1630, P854, P813, P248).

## 0.6.3
- A copy whose base URI is the published site stands without pointing to its source (DCAT landing page, `dcterms:source`).

## 0.6.2
- Fixes: meta description on two-language sites, copy button copies only addresses of the site itself. The Original tab is gone.

## 0.6.1
- Forwarding pages `entity/Q101.html` for the concept URIs under the published site.

## 0.6.0
- The `references` query no longer builds a cross product (85 s to under 1 s); every entity page links its Turtle and JSON file and has a
  copy button for the concept URI.

## 0.5.0
- The RDFS bridge of the kernel (`wdt:P1` to `wdt:P3` as sub-properties of `rdfs:subClassOf`, `rdf:type`, `rdfs:subPropertyOf`) in the RDF export.

## 0.4.0
- Dummy Wikibase from CSV tables and a kernel (Q1 to Q3, P1 to P10): `from-csv`, `to-csv`, `csv-fmt`; Wikidata ids read as links.

## 0.3.1
- Free query editor `query.html` (SELECT, ASK, CONSTRUCT over the Turtle file) with table, map and image views.

## 0.3.0
- RDF export in the Wikibase model with DCAT 3, one Turtle file per entity, and the query page `sparql.html` that runs in the browser.

## 0.2.0
- Search box with autocomplete and its index (label, alias, id; case and accent insensitive).

## 0.1.0
- First version: orchestrator `main.py` with one module per step; incremental harvest of a Wikibase (`--probe`, from-dir fallback);
  loader and validator; static pages laid out like a Wikibase (sidebar, tabs, one box per property, language switch, Leaflet maps);
  CI with the strict pipeline, link check and two-run determinism check, and the reusable Pages workflow `site.yml`.
