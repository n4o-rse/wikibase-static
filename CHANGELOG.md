# Changelog

Every version is a tag `vX.Y.Z` on the commit that raised `__version__` (`tools/tag_versions.py` makes the missing tags;
`0.1.0` is the last commit before 0.2.0). The newest version is on top. The work plan with the findings behind each version is `PRIMER.md`.

## 0.32.0
- `check-crm` works on every site. Its shapes took P1 and P2 of the kernel as "subclass of" and "instance of", so on a harvested Wikibase they flagged
  the items (the subjects of P1 where P1 is "instance of") and, with Q1 to Q3 left out unconditionally, missed real classes at those ids.
  The targets now come from `Site.class_properties()` and Q1 to Q3 are left out only on a site with the kernel; kernel sites check as before.
- New value `model` in the column `crm_class` of `data/crm.csv`: the class belongs to the data model (a vocabulary class, a SKOS class, a role) and is
  not anchored in the CIDOC CRM on purpose. The mark holds for the classes below it unless one has a CRM class of its own (an anchor wins).
  `load` counts such classes as "marked model" and no longer lists them as missing, `check-crm` leaves them out ("N model class(es) not checked"),
  the page of such a class says "none: a class of the data model, not anchored on purpose" instead of "none yet". A class with a CRM row and the mark
  is a problem and keeps the CRM class.
- 6 new tests (768 in all).

## 0.31.0
- The CIDOC CRM overlay (`data/crm.csv`) works on every site, not only on one made by `from-csv`. Until now the CRM class and the inherited-from class
  appeared on the page of an item, and `rdfs:subClassOf` / `rdf:type` were written out, only when the site had the N4O kernel (Q1 to Q3, P1, P2).
  A harvested Wikibase (`wb-squirrelbase-static`, `wb-n4o-prov-static`, `wb-fuzzysl-static`) has other numbers (P1 instance of and P2 subclass of
  on one, the other way round on another) and a copy of Wikidata has P31 and P279, so the overlay showed nothing there.
- New `Site.class_properties()`: with the kernel P2 and P1; otherwise the properties of the datatype `wikibase-item` whose English label is
  "instance of" or "subclass of", and Wikidata's P31 and P279 when statements use them and the site does not hold the property. `crm_edges()`,
  `crm_classes()`, the page (`crm_rows`) and `rdf.spell_out()` use it. Without any such property nothing is inherited, as before; with the kernel
  nothing changes (the output of a kernel site is the same as in 0.30.1). Without the kernel only edges to an item of the site are written out.
- `crm.CLASSES` knows E5 Event, E21 Person, E26 Physical Feature, E40 Legal Body and E78 Curated Holding by their short code.
- 7 new tests (762 in all): either numbering of Wikibase Cloud, a copy of Wikidata, a property with another label, the spelled-out tree and the N4O anchor test.

## 0.30.1
- The Site workflow no longer fails for a site that has no `data/derived/` (one that is only harvested, such as `wb-squirrelbase-static` and
  `wb-n4o-prov-static`). The step "The output is the same after run 2" hashes `docs/`, `dist/` and `data/derived/`; `find` exits with 1 when a folder
  is missing, and the shell of the job runs with `pipefail`, so the step ended with exit code 1 (the first hash step hid it behind `echo`). `find` is now
  `{ find ... || true; }`: a missing folder has no files. A site that has the folder is hashed as before. 1 new test (755 in all); it runs both steps
  under `bash -eo pipefail`, with and without the folder (skipped on Windows). Callers use `@main`, so no site has to change anything.

## 0.30.0
- Satellites that are a static copy of a Wikibase (`wb-squirrelbase-static`, `wb-n4o-prov-static`, S13a). `tools/new_satellite.py --wikibase URL`
  writes the folder from `tools/satellite-template-wikibase/`: the wrapper `main.py` with the verbs `harvest` (the first run takes the address
  from `source.url` of `site.yaml`, so it is written down once) and `fetch-logo`, `site.yaml` with the source, own URIs (`rdf_base` = the Pages
  address) and the prefix family, the two workflows (`deploy: true`), `harvest.cmd` and `update.cmd`, README, PRIMER. `docs/` and
  `data/derived/` are not committed; `data/raw/` and `dist/` are. No seeds and no CSV tables: the data come from the harvest. The first run is
  one line (printed at the end): `harvest --probe`, `harvest`, `fetch-logo`, `--strict`, commit, push.
- New step `fetch-logo` (`step_fetch_logo.py`): asks the Wikibase for the logo it names in its site information, saves it as `assets/logo.<ext>`
  and writes `logo:` in `site.yaml` (the rest of the file stays as it is), so the pages never load the image from the source. `--file PATH`
  takes an image you saved yourself. A bot challenge (Anubis) ends the step with exit code 2 and is not worked around, as in `harvest`.
- `tools/satellites.txt`: the two Wikibase satellites are in the list.
- 21 new tests (754 in all).

## 0.29.0
- The CI builds and publishes the site; `docs/` and `data/derived/` need not be committed any more. `.github/workflows/site.yml`
  (reusable): the Pages artifact is made in the `check` job from the very build that was checked (the `deploy` job only
  publishes it), and after run 2 a hash over `docs/`, `dist/` and `data/derived/` must equal the one after run 1, so the
  determinism check also covers folders that are in `.gitignore`. Whatever is committed is still compared with a fresh build
  (`git status`). A repository that commits `docs/` works as before; nothing has to change in a caller.
- `tools/untrack_output.py`: changes a site repository over. It checks that the repository is clean and that GitHub Pages is
  served by GitHub Actions (a site served from the branch would vanish), moves `docs/` and `data/derived/` away, builds from
  the sources and compares: a file only the committed folder has (made by hand) stops it and everything is put back. Then it
  writes `.gitignore`, takes the folders out of the index (`git rm --cached`) and prints the one-line commit. `--check` only
  tests. `dist/` stays in git (the cited products).
- `tools/satellite-template/`: new satellites start without `docs/` and `data/derived/` in git (`.gitignore`).
- 11 new tests (733 in all).

## 0.28.2
- Dates in the Julian calendar are imported. `import-wikidata` used to drop every date that was not Gregorian, which lost e.g. the
  inception (P571) of 71 Irish round towers (centuries of the Julian calendar). The CSV form of such a date is the full form with
  a calendar suffix: `+1100-00-00T00:00:00Z/7/julian` (`/gregorian` is the default and is left out). `csvio.parse_time` reads it,
  `format_time` writes it, `to-csv` no longer reports the calendar model as lost for Julian dates. RDF (`wikibase:timeCalendarModel`)
  and the pages ("11th century (Julian)") knew the Julian model already. Other calendars and dates finer than a day are still
  not imported and are counted in the report. 1 new test, 1 changed (722 in all).

## 0.28.1
- `tools/new_satellite.py` and `tools/satellite-template/`: the skeleton of a new satellite site that is a set of Wikidata items
  (`wd-ogham-static` and the sites after it). One call writes the folder: the wrapper `main.py` (`import-wikidata` with `--generic
  --provenance item`), `site.yaml` (prefix, `entity_files: false` and `browser_graph: slim`, or both off with `--small`), the two
  workflows (`deploy: true`), README, PRIMER, CITATION, empty CSV tables, the seed queries (`--query`, `--qids`) and the logo. The pin
  in `requirements.txt` is the version of the package. The first run is one line (printed at the end): `seeds-from-sparql`,
  `import-wikidata`, `--strict`, commit, push. 7 new tests (721 in all).
- `tools/satellites.txt`: the Wikidata sites are in the list.

## 0.28.0
Slimmer sites, for a Wikidata set of a thousand items and more (`wd-ogham-static`, 1246 seeds: 202 MB in `docs/`, 62 MB in `data/derived/`,
a 12.8 MB Turtle file that the query page had to parse in the browser). Everything is optional; without the new settings nothing changes.
- `import-wikidata --provenance item`: only the `P4` statement of an item names its Wikidata page, the retrieval date and Wikidata as the
  source (`P6`, `P7`, `P8`); the statements keep just the references Wikidata gave them (numbered from group 1). The default,
  `--provenance statement`, is the old behaviour (those three on every statement). On the replica with 1246 items this took 79 394
  reference rows down to 4 747 and `data/derived/` from 62 MB to 23 MB.
- `site.yaml`: `entity_files: false` writes no `docs/ttl/<ID>.ttl` and `docs/json/<ID>.json`, no download links on the entity pages, no
  per-entity DCAT distributions of those files (the HTML page stays a distribution), and the `entity/<ID>.html` stubs name no files.
  The complete Turtle file stays in `downloads/`. The `distributions` example query is left out then.
- `site.yaml`: `browser_graph: slim` publishes `downloads/<host>.slim.ttl`, the export without the DCAT description of each entity
  (the datasets stay as `a dcat:Dataset`, the catalogues still count them); the query page loads and queries that file, and links the
  complete one. `rdf.slim()` makes it. The saving is small (9 % of the triples on the replica) because the statements are the bulk.
- Tests: 6 new (3 `--provenance`, 3 for the switches; 714 in all).

## 0.27.1
- `import-wikidata`: a Wikidata item that was only a *stub* in an earlier run (labels, descriptions, aliases) and is a seed now is
  fetched again in full. Before, `refresh` compared only the revision, so such an item kept its stub copy and stayed without
  statements (found in the first real run of `wd-govanstones-static`: the 31 stones were stubs of the collection item, became seeds
  through the new query, and came out with the twin only; `item Q113 is not an instance of a class`). A stored copy without
  `claims` counts as not current when the full item is wanted.

## 0.27.0
- `import-wikidata --generic` (S14a): for a site that is a set of Wikidata items and has no model of its own. A Wikidata property
  without a twin is not only reported but created as a local property (`P100` and up, `origin=wikidata`, numbered through
  `idmap.csv` with the key `P18`): labels, descriptions and aliases from the Wikidata property, its datatype, the twin `P4` with a
  reference `P6`, and for an external identifier the formatter URL (Wikidata `P1630`) in the local formatter property. Properties
  with a datatype the CSV cannot hold (geo-shape, tabular data, ...) are reported, not created; `--skip-property P2671,P646` leaves
  out properties that only add noise. An existing twin (the kernel's, a hand-made one) is used as before. The class stubs of
  "instance of" targets hang below the root of the class tree. Without `--generic` nothing changes.
- The online run fetches the Wikidata property entities of the created properties in full (one request per 50), and a second run asks
  only for revisions as before; `--from-dir` stores saved property files (`P18.json`) as well as item files.
- `seeds-from-sparql`, a verb of its own (network): `data/seeds/wikidata-<name>.rq` (a query for the Wikidata Query Service that returns
  `?item`, optionally `?kind` and `?itemLabel` or `?note`) and `data/seeds/wikidata-qids.txt` (single ids with a note) become
  `data/csv/seeds-wikidata.csv`. The answers are kept in `data/raw/wikidata-seeds/<name>.json` (canonical, so a change shows in git);
  `--offline`, `--from-dir DIR` (a JSON download from query.wikidata.org), `--dry-run`, `--max-seeds` (default 2000). `note` and
  `instance_of` of a seed that stays are kept; a seed that no source names any more is dropped from the list and said.
- `IdMap.get_property` numbers properties from `P100` on, apart from the items.
- Tests: 707 in the repository.

## 0.26.1
- `tools/satellites.txt` lists three more site repositories: `osm-sisal-static`, `osm-ogham-static`, `osm-holywells-static`.
- `tools/rollout.py` (and so the update workflow) also pins a requirement that has no ref at all (`...wikibase-static.git`, which follows
  the default branch): it gets `@vX.Y.Z`.
- Tests: 667 in the repository.

## 0.26.0
- `.github/workflows/update.yml`, a reusable workflow for the site repositories: it looks for a newer release of wikibase-static, changes the
  pin in `requirements.txt`, builds the site twice with `--strict` (and runs `check_attribution.py` where there is one) and opens a pull
  request; merging it starts the Site workflow as usual. `examples/update-caller.yml` is the caller (every morning and by hand).
  Once per repository: Settings, Actions, General, tick "Allow GitHub Actions to create and approve pull requests".
- `tools/rollout.py`: `--here` does the first half for the repository in the current folder (what the workflow runs); the package is
  installed once per run, not once per repository, which saves most of the time of an update of several repositories.
- Tests: 666 in the repository.

## 0.25.0
- The version of the package is no longer written into every page and every entity file, so a new release does not change what did not
  change. The footer has an empty `<span data-wbs-version>`; the build writes `assets/version.js` (one small file) that fills it. The
  entity Turtle files (`ttl/Q1.ttl`) say "Generated with wikibase-static; data as of …" without the number; the Turtle files of the
  whole dataset (`downloads/<site>.ttl` and `dist/`) keep it. After an update, only `version.js`, those two files and the assets that
  really changed differ, instead of every page (the first update to 0.25.0 rewrites the footers once). 20 asset files instead of 19.
- `tools/rollout.py` brings the satellite repositories listed in `tools/satellites.txt` to a version: pull, change the pin in
  `requirements.txt`, `pip install --upgrade --force-reinstall`, `main.py --strict` twice (and `check_attribution.py`), commit, a third
  build as the check of the CI, push. `--dry-run`, `--only NAME`, `--no-push`, `--force`.
- Tests: 663 in the repository.

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
