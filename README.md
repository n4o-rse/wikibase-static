# wikibase-static

Static, read-only HTML demonstrators for Wikibase instances.

`wikibase-static` archives an existing Wikibase (for example one hosted on
Wikibase Cloud) through its public API, or builds a dummy Wikibase from CSV,
and publishes the result as a static site on GitHub Pages. The site looks and
navigates like a Wikibase: item and property pages, statements with qualifiers
and references, clickable Q- and P-ids, external links in a new tab, maps for
coordinates, Commons images, a search box and an in-browser SPARQL query editor with table, map and image views. Nothing
on the published site can be edited.

> **Status.** `harvest` (S4), `load` (S2), the page renderer `build` (S3), the search `search` (S5) and the
> RDF export, example queries and query editor `rdf`, `sparql` (S6) work, and so does the CSV route (S7a: `from-csv`, `to-csv`,
> `csv-fmt`; S7c: `import-open-archaeo`; S7d: `import-wikidata`; S7e: `apply-qs`; S7h/S7i: `merge`). The push into a real Wikibase
> (S7g) is still to come. See [`PRIMER.md`](https://github.com/n4o-rse/wikibase-static/blob/main/PRIMER.md) (German) for the plan, the
> decisions taken so far and the order of the steps.

## Workflow

```
Wikibase (API)  --harvest-->  data/raw/      Wikibase JSON, unchanged, incremental
CSV             --from-csv->  data/derived/  the same format for a dummy Wikibase
                                  |
                                  +--build-->  docs/   static pages, search index, map
                                  +--rdf---->  dist/   RDF in the Wikibase data model (+ DCAT), per-entity files in docs/
                                  +--sparql->  docs/   example queries and query editor, running in the browser
```

Two properties are part of the design and are checked, not hoped for:

* **Incremental and polite.** `harvest` compares revision numbers with a manifest
  and downloads only what changed. It identifies itself with a User-Agent and
  contact address, throttles its requests and stops when a host asks it to prove
  it is a person; it never tries to get around such a protection.
* **Deterministic.** Running the pipeline twice leaves `git status` clean. No
  generator reads the clock.

## Usage

Python 3.10 or later. `harvest` and `load` need no third-party packages; `build` needs PyYAML and Jinja2
(`pip install -r requirements.txt`, or install the package, which brings both).

```cmd
python main.py --list
python main.py --dry-run
python main.py
python main.py --strict
```

`harvest` touches the network and is therefore not part of the default run. Run it
in the repository of the site you are building (set `WBS_ROOT` to its folder), so
that `data/raw/` of this package repository stays empty. One Wikibase per `data/raw/`.

```cmd
set WBS_ROOT=C:\path\to\fuzzy-sl-static&& python main.py harvest --probe --url https://fuzzy-sl.wikibase.cloud
set WBS_ROOT=C:\path\to\fuzzy-sl-static&& python main.py harvest --url https://fuzzy-sl.wikibase.cloud
set WBS_ROOT=C:\path\to\fuzzy-sl-static&& python main.py harvest
set WBS_ROOT=C:\path\to\fuzzy-sl-static&& python main.py harvest --from-dir C:\path\to\saved-json
```

`--probe` makes one request and writes nothing. The second command downloads the
entities; the third (the address is remembered in `data/raw/manifest.json`) fetches
only what changed. If the host answers with a bot challenge such as Anubis, the
step stops with exit code 2 and does not try to get around it: save the entity JSON
in a browser and use `--from-dir`. Set a contact in the User-Agent with
`--contact` or the `WBS_CONTACT` environment variable.

`load` reads `data/raw/entities` and `data/derived/entities`, checks them and prints the counts
and warnings (`--all` prints every warning). It writes nothing and runs with the default steps:

```cmd
python main.py load
```

`build` renders the loaded entities into `docs/`: `index.html` (title, description, counts), `items.html` and
`properties.html` (the lists), `overview.html` (the items grouped by the class they are an instance of, one
section per class, with a map of the instances that have coordinates; it appears when the site has an
"instance of" property: `P2` with the kernel, otherwise the property labelled "instance of"), one flat page per
entity (`Q123.html`, `P1.html`) and `assets/`. It needs no network. The pages are laid out like a Wikibase: a sidebar with the
logo and a short navigation, tabs, a table of labels, descriptions and aliases per language, and one box
per property with its statements (rank, value, qualifiers as label and value pairs, references behind a
"N references" toggle). Links between Q- and P-ids show the id behind the label, external links open in a
new tab. Every coordinate on Earth gets a map (Leaflet, OpenStreetMap tiles), Commons images are shown
through `Special:FilePath`, and the footer carries the source, the date of the last change and the licence
(CC0 1.0, Public Domain, unless `site.yaml` says otherwise). With a second language in
`site.yaml` the pages have a language switch. The step then checks its own output: pages against
entities and every internal link. Problems are `WARN` lines, `--strict` turns them into errors.

```
python main.py build
```

`search` writes the index for the search box that `build` puts into the tab row of every page
(`docs/assets/search-index.js`). Run it after `build`; the default run does. The box finds an entity by
its label, by an alias (in any language, not only the two of the site) or by its id (`Q97`, `q9`), ignoring
case and accents; "uber" finds "Über". It offers up to ten hits, labels ahead of aliases and whole strings
ahead of parts, and shows the matching alias next to the label when that is why an entity appears. Arrow
keys and Enter work as in any combobox, and the list follows the language switch. Descriptions are shown
but not searched. The index is a script file that is loaded the first time the box is used, so a page that
is only read costs nothing, and the search works when `docs/` is opened from a disk (`file://`). The index
depends on the data and the two languages of `site.yaml` and on nothing else, so two runs give the same
bytes. Without JavaScript the box is not shown. If the site has no entities, the step does nothing.

```
python main.py search
```

`rdf` writes the data as Turtle in the RDF model of Wikibase itself (`wd:`, `wdt:`, `p:`, `ps:`, `pq:`, `pr:`, value
nodes, ranks; the mapping follows the RDF dump of Wikibase, so a query written for its Query Service runs on the
file). The URIs are those of the real Wikibase (`source.url`, or `rdf_base` in `site.yaml`). The export describes
itself with DCAT 3: one `dcat:Catalog` for the Wikibase (with a catalogue for the items and one for the properties),
one `dcat:Dataset` for every entity record (the `data:Q1` node Wikibase already types as `schema:Dataset`) and one
`dcat:Distribution` for each file that exists: the archived JSON, the HTML page and the Turtle file of that
entity. Distributions need download URLs, so they appear when `pages_url` is set. Files:

```
dist/<host>.ttl                         everything (for https://example.wikibase.cloud: example.wikibase.cloud.ttl)
docs/downloads/<host>.ttl               the same file, as published
docs/downloads/wikibase-ontology.ttl    the Wikibase system ontology (CC0), converted from ontology.owl of Wikibase
docs/ttl/Q1.ttl                         the triples of one entity with its DCAT description
docs/json/Q1.json                       the entity as archived, byte for byte
```

The file is built as sorted N-Triples and written from there by the package's own Turtle writer, then read back
with rdflib and compared; two runs give the same bytes. Values Wikibase cannot express in RDF (a decimal that is
not a number, a language code that is not a tag) and data types the site cannot show are reported as `WARN`.
Differences from a real dump (own hashes for reference and value nodes, no normalised `wdtn:` URIs, no sitelinks)
are listed in `PRIMER.md`, A4.

```
python main.py rdf
```

`sparql` builds `docs/sparql.html`: example queries in editable boxes, Run and Reset, results as tables, every query
also as a plain `.rq` file in `docs/downloads/queries/`. Nothing is loaded until somebody presses Run; then Pyodide
(from cdn.jsdelivr.net) and rdflib (from PyPI) start in the browser, which fetches the Turtle file of the site and
runs the query itself, so no endpoint is needed and nothing typed leaves the browser. The default queries fit every
Wikibase (items, properties, how often a property is used, aliases, links between items, coordinates, qualifiers,
references, ranks, the DCAT catalogues); a query for data the site does not have is left out. To use your own,
write `queries.yaml` in the repository root (schema in `py/wikibase_static/sparql.py`; `@@lang@@` stands for the
default language). **Every query is executed at build time, with the very Python the page runs, against the file the
page serves, and a query that returns no rows is a `WARN`** (an error under `--strict`): SPARQL answers a mistyped
IRI with no rows, so an empty example is the usual symptom of a broken export.

`docs/query.html` is the free editor, in the manner of the Query Service of Wikidata (without its chart types). It holds
any SPARQL query (`SELECT`, `ASK`, `CONSTRUCT`; Ctrl+Enter runs it) and a list of the example queries to start from. A result is
a table; it is also a **map** when a column holds `Point(longitude latitude)` values (Wikibase coordinates), and **pictures** when a
column holds image files (a Commons file, or any URL that ends in `.jpg`, `.png`, `.svg` and the like). A comment line
`#defaultView:Map`, `#defaultView:ImageGrid` or `#defaultView:Table` at the top of a query chooses the view that opens first. A
table can be downloaded as CSV or as SPARQL Results JSON, and "Copy link to this query" puts the query into the address
(`query.html#q=...`) so it can be sent around. Each example on `sparql.html` has a link that opens it in the editor.

```
python main.py sparql
```

`site.yaml` in the repository root is optional; every key has a default:

```yaml
title: My Wikibase
description: One line for the start page
logo: assets/logo.png            # a file in the repository (copied to docs/assets/logo/), or a URL;
                                 # a logo with a white background blends into the grey sidebar
colour: "#336699"                # accent colour, hex
source:
  url: https://example.wikibase.cloud   # must match data/raw/manifest.json
license:                         # optional; without it the footer says CC0 1.0 (Public Domain)
  name: CC BY 4.0                # text, shown as given
  url: https://creativecommons.org/licenses/by/4.0/
languages:
  default: en
  second: de                     # optional: adds the language switch
imprint: https://example.org/imprint    # text or URL
pages_url: https://example.github.io/repo/   # optional, for the canonical link
formatter_property: P1630        # property that holds the formatter URL of external-id properties
rdf_base: https://example.org    # optional: base URI of the RDF export; default is source.url
rdf_prefix: chb                  # optional: own prefix family (chb:, chbt:, chbp:, ...) instead of wd:, wdt:, p:, ...; see "Prefixes of the export"
data_as_of: 2026-10-25           # optional: date (or date and time) of the data, for entities without a modification time of their own (CSV tables); used in the header and the catalogue of the RDF export, else "unknown"
edit_url: https://github.com/OWNER/REPO/edit/main/data/csv   # optional: folder of the CSV tables in the repository editor (tab "Source rows")
counterpart:                     # optional: the same entities in a real Wikibase; see "Counterpart in a real Wikibase"
  name: wiki.example
  uri: https://wiki.example/entity/{id}
  url: https://wiki.example/wiki/Special:EntityPage/{id}
  map: data/idmap-wiki.example.csv
```

Offline tests (a fake Wikibase on localhost, no network needed):

```cmd
python -m unittest discover -s tests
```

The tests of the search box and of the query page run the code of `search.js` and `sparql.js` under Node.js; where `node` is not on the
path they are skipped, and the other tests are unaffected.

### Importing open-archaeo (S7c)

```
python main.py import-open-archaeo               about 100 of the entries, stratified by category
python main.py import-open-archaeo --limit 40    another size (the same limit always picks the same entries)
python main.py import-open-archaeo --all         every entry
python main.py import-open-archaeo --dry-run     print the report, write nothing
```

Offline, and a verb of its own because it writes source files. It reads `data/raw/open-archaeo-software.csv` (the output of
`py/transform.py` in open-archaeo, never edited), a mapping `data/csv/mapping/open-archaeo.csv` (columns `column, property, qualifiers,
rule`; the properties are Wikidata properties, turned into the local ones through their `P4` twins) and a vocabulary
`data/csv/mapping/open-archaeo-vocabulary.csv` (controlled values and the Wikidata item each stands for, where there is one). It
writes rows with `origin=open-archaeo` into the four tables and `idmap.csv`; `from-csv` then makes the JSON. Every statement carries
a reference (P6, the page of the entry). A reimport replaces the rows of the importer; a row whose `origin` you emptied counts as
written by hand and wins (the importer then leaves that property of that subject alone). The report lists what was not imported
and why. The rules are described at the top of `py/wikibase_static/step_import_open_archaeo.py`.

### Importing Wikidata items (S7d)

```
python main.py import-wikidata                  fetch what changed at Wikidata, then import the seeds
python main.py import-wikidata --offline        no network: import what data/raw/wikidata/ holds
python main.py import-wikidata --from-dir DIR   store JSON files saved in a browser (Special:EntityData, wbgetentities), then import
python main.py import-wikidata --dry-run        print the report, write nothing
```

The only importer that may use the network, so it has a verb of its own and is never part of the default run. The seeds are listed in
`data/csv/seeds-wikidata.csv` (columns `qid, kind, note` and, optionally, `instance_of`; `kind` and `note` are for the reader; `instance_of` lists local item ids
separated by `|`, e.g. the class of the chublets: the seed becomes an instance of them besides what Wikidata says, once, without a
Wikidata reference). Each seed becomes a local item
(`origin=wikidata`) with its labels, descriptions, aliases (`--languages`, default `en,de`), statements, qualifiers and references.
The raw answers are kept unchanged in `data/raw/wikidata/entities/` with a `manifest.json`; a run asks Wikidata for the revisions
(`props=info`, 50 ids per request) and fetches only what changed. The requests carry no `maxlag` (Wikidata counts the lag of its
query service in it, which is often above five seconds and says nothing about reading); `--maxlag N` switches it on.

Wikidata ids stay out of the data: a Wikidata property is translated through the `P4` twin of a local property (one without a twin is not
imported and appears in the report and in `dist/wikidata-gaps.csv`), an item value through the twin of a local item. A target without a
twin becomes a *stub* (`origin=wikidata-stub`: label, description and the twin, nothing more); a target that is the value of
"instance of" becomes a class stub below the local twin of software. Every statement carries a reference (the Wikidata page, the
date of the revision that was read, stated in Wikidata), followed by the references Wikidata itself holds. A reimport replaces the
importer's rows; a row whose `origin` you emptied wins. The report also lists which repository and exact-match URLs of the seeds occur in
items of another origin (open-archaeo); nothing is merged. The rules are described at the top of
`py/wikibase_static/step_import_wikidata.py`.

### Merging items (S7h)

The same thing can arrive twice, once from Wikidata and once from open-archaeo. `python main.py merge Q381 Q359` merges the first
item into the second, as Wikibase does with `Special:MergeItems`; `--dry-run` says what would happen, `--list` shows the merges,
`--undo Q381` takes one back. The command writes one line to `data/csv/merges.csv` (`from, to, note`); the tables themselves stay
as they are, and `from-csv` applies the merges while it reads them, so a merge survives every reimport.

Statements of the merged item move over; one the target has already is not doubled and its references are joined; different values
of the same property are all kept and named in the report. The label of the target wins and a different label of the merged item
becomes an alias. A value that pointed at the merged item points at the target. The merged item is a redirect from then on: its page
forwards, the RDF says `owl:sameAs`, its id is never used again. Chains are refused (the target must not be merged into something
else), and so is a property or a pair of an item and a class.

`python main.py merge --suggest` looks for items that may be the same thing and writes `dist/merge-suggestions.csv`, one line per pair with
the command that would merge it. It compares items of different origin by name (labels and aliases in every language; case, accents and
punctuation do not count), by first and last name ("Allard Mees", "Allard Wijnand Mees") and by account names that look like initial plus
surname ("nfrerebeau"). Nothing is merged by it; you run the lines you agree with. The Wikidata side is the one that stays.

### Changing the tables with QuickStatements (S7e)

The tables stay the state, and a QuickStatements file is the language of a change. `python main.py apply-qs data/edits/my-change.qs`
reads a subset of QuickStatements v1 (tab separated, one command per line, `#` comments) with explicit local ids and writes the change
into the CSV tables in their canonical form; `--dry-run` says what would happen. Commands: `CREATE` and `LAST` for a new item (it gets
the next free Q number), `Len`, `Dde`, `Aen` for label, description and alias, `Q12<TAB>P3<TAB>value` for a statement with further
pairs as qualifiers, `S`-numbered pairs as references, a leading `-` to remove exactly one statement (or alias), and
`MERGE<TAB>Q12<TAB>Q13`, which writes a line to `merges.csv`. Values: `Q12`, `wd:Q42`, `"text"`, `de:"Text"`,
`+2021-06-04T00:00:00Z/11`, `@lat/lon`, `12`, `somevalue`, `novalue`; each is checked against the datatype of its property.

A file is applied all or nothing: every line is checked first and named with its line number, the tables are built once more with the
change, and one bad line leaves everything as it was. A statement that is there already is not added twice. `data/edits/applied.csv`
(`sha256, file, changes`) keeps the hash of every applied file, so the same text does not act a second time, whatever its name or line
ends. What the subset does not read (sitelinks, `CREATE_PROPERTY`, removing a label) is reported as `WARN` with the line number and skipped.
New rows have no `origin`, so they count as hand work and no importer overwrites them. The exact syntax is in the docstring of
`py/wikibase_static/step_apply_qs.py`.

### Prefixes of the export (S16)

By default the Turtle files use the prefix names of Wikidata (`wd:`, `wdt:`, `wds:`, `p:`, `ps:`, `pq:`, `pr:`, `wdref:`, `wdv:`), which is right when
the base URI is that of the real Wikibase. A site whose base URI is its own address (a demo on GitHub Pages) should not borrow them: a
reader takes `wd:Q933` for an item of Wikidata. Set `rdf_prefix: chb` and the family becomes `chb:` (entities), `chbs:` (statement nodes),
`chbt:` (direct claims), `chbp:`, `chbps:`, `chbpsv:`, `chbpq:`, `chbpqv:`, `chbpr:`, `chbprv:`, `chbno:`, `chbref:`, `chbv:`, plus `chbdata:`, `chbcat:`
and `chbdist:`. The namespaces do not change, only their names, so the graph is the same. The query page declares the same prefixes.

With a family the Turtle file of an entity is `<base>/ttl/<ID>.ttl` (Wikibase's own `Special:EntityData/<ID>` does not exist on a static host) and the dataset it belongs to is `<base>/ttl/<ID>.ttl#dataset`, so that the dataset and the file (the `dcat:downloadURL` of its Turtle distribution) are two things.
Only `chb:<ID>` opens a page (`entity/<ID>.html`, which forwards to the page of the entity); the IRIs of statements, references, values and property
paths are identifiers and do not resolve.

### Counterpart in a real Wikibase (S7g)

A site made from CSV tables has its own numbers (`Q107`). When the same tables were pushed into a real Wikibase with
`wikibase-federation` (`usecases/chublets`), that Wikibase gave the entities numbers of its own (`Q11`) and the push wrote the
pairs into `idmap-<target>.csv`. Copy that file into this repository and name it under `counterpart:` in `site.yaml`
(`name`, `uri` with `{id}` for the concept URI, `url` with `{id}` for the page, `map` for the file; `url` defaults to `uri`).

Then every entity page has the line "The same entity in <name>: Q11" with a link that opens the page there in a new tab,
the Turtle file of the entity says `owl:sameAs <uri of the counterpart>`, the table is published as
`downloads/<file name>` and the start page links to it. Entities without a row (the Wikidata stubs, which the push never creates)
have none of this. A row that is not a pair of ids of the same kind, a second row for the same id, a row for an id that the site does not
have and a missing table are warnings; nothing is guessed. The table needs the columns `source_id` and `target_id`; others are ignored.

### Data-model graphics (S16)

Every entity page has a section "Statement graph": the entity on the left, one box per property, the values to the right, qualifiers as chips,
references that belong to one statement as dashed chips and a reference that several statements share once at the bottom. Item values link to
their pages. The start page has the section "Data model": one card per class with the properties its instances use, the class or data type of
the values and the number of statements. It is read from the data, so it shows what the data does and not what a schema says. The same picture
is `docs/graphs/model.svg` (links with `../`). The colours are fixed in the SVG (real object dark green, class dark orange, other items pale grey,
properties and statement metadata amber, literals white), so the picture looks the same on the page, as a file and in a paper. The code is
`py/wikibase_static/modelgraph.py`. Classes whose instances are exactly the same items share one card (header "software · Little Minion"), because their rows would be the same. A long name of the entity in the middle is set on two lines. Under every graphic there are the buttons "Download as SVG" and "Download as PNG" (they work in the browser, `app.js`: the SVG of the page with absolute links, the PNG at twice the size on a white ground; without JavaScript they stay hidden). It needs no network and no layout engine and draws the same picture every time.

### Class hierarchy

On the overview, under the heading of every class, and on the page of every class that has superclasses or subclasses, there is the whole
hierarchy around that class: every path from the root down to it, with the class itself in bold in the middle, and everything below it.
A class with two superclasses stands under both. The branches above hold only what leads to the class (no siblings). With the kernel, its root "Instance" (Q3) is left out of the trees (it tops every branch and says nothing); only the page of Q3 itself shows it. It uses "subclass of"
(P1 where the kernel is part of the site, otherwise the property with that English label), so a harvested Wikibase gets it too.

### Source rows (S7f)

When the site is made from CSV tables (`data/csv/` exists), every entity page has a tab "Source rows" next to "Read". It opens a section with
the rows of the CSV files that the page is made from: the entity's row in `entities.csv`, its rows in `statements.csv`, the rows of
`qualifiers.csv` and `references.csv` that belong to those statements, and the lines of `merges.csv` that name it. The text is the text of
the file, line for line, with the header line first, and each block has a button that copies it. With `edit_url` in `site.yaml` every block
links to its file in the repository editor. The kernel (Q1 to Q3, P1 to P10) is shown from the tables of the package, without a link.
The page stays read-only; there is no write access from the browser. A site that was harvested from a Wikibase (no `data/csv/`) gets no tab,
and its pages do not change.

### CIDOC CRM overlay

A site can say which CIDOC CRM class its classes stand for, without touching the data. Write `data/crm.csv` next to
`data/raw/` (columns `class, crm_class, note`; one row per class, `crm_class` as `crm:E73`, `crmdig:D14`, `crmsci:`,
`crmarchaeo:` or `crmgeo:` plus the number). The row is inherited along instance of and subclass of, so one row at the
root class anchors the whole tree; an own row comes before an inherited one, and several rows give several classes.
`load` reports the classes that have none, entity pages show the class (and the class it comes from), `rdf` writes
`rdfs:subClassOf <crm class>` in a section of its own and, for an extension class, the chain up to the first `crm:` class
(D14 to D1 to E73), so that tools which follow `rdfs:subClassOf` to CIDOC CRM reach it. The default query `crm-classes`
lists the result. Without `data/crm.csv` nothing changes. The overlay needs the kernel (Q1 to Q3, P1, P2) of a site made by `from-csv`.

The export also ties the DCAT classes it uses to the CRM (`data/dcat-crm.csv` of the package: `dcat:Dataset` is an E73, `dcat:Catalog` an
E31 and a D1, `dcat:Distribution` a D1) and, with an overlay, writes `subclass of` / `instance of` as plain `rdfs:subClassOf` / `rdf:type`,
because the N4O profile does not infer. `python main.py check-crm` (not part of the default run) validates `dist/<host>.ttl` with pySHACL
against `data/shapes-crm.ttl`: a class of the site or a DCAT class that reaches no CIDOC CRM class over `rdfs:subClassOf` is a violation
(`WARN`, so `--strict` stops), one that reaches only E1 is a warning.

## Continuous integration

Two workflows live in `.github/workflows/`:

- `ci.yml` guards this repository: the unit tests (Ubuntu with Python 3.10 and 3.13, Windows with 3.13), then
  `python main.py --strict` twice, with `git status --porcelain` required to be empty after each run.
- `site.yml` is a reusable workflow for a site repository (a demo, or a repository made from the template).
  It runs the same strict pipeline twice, fails if the committed `docs/` and `dist/` differ from a fresh build,
  and on the default branch publishes `docs/` to GitHub Pages. A dead internal link is a `WARN` line of the
  build step, so `--strict` turns it into a red run.

To use it in a site repository, copy [`examples/site-caller.yml`](examples/site-caller.yml) to
`.github/workflows/site.yml` and set Settings → Pages → Source to "GitHub Actions". The repository's
`requirements.txt` must install `wikibase-static`; `python main.py --strict` is the default command and can be
changed with the `command` input.

## Layout

```
main.py                     the only entry point
py/wikibase_static/         the package (one module per step, utils.py, model.py, loader.py, render.py,
                            site_config.py, rdf.py, counterpart.py, modelgraph.py, sparql.py, data/ (default queries, ontology), templates/,
                            static/ with app.js, search.js, sparql.js, map.js, style.css
                            and a copy of Leaflet 1.9.4)
data/raw/                   harvested JSON, as obtained
data/derived/               intermediates made from CSV
dist/                       versioned products: RDF, pipeline report
docs/                       the site, served by GitHub Pages
.github/workflows/          ci.yml (this repository), site.yml (reusable, for site repositories)
examples/                   site-caller.yml, the few lines a site repository needs to call site.yml
PRIMER.md                   work plan and decisions (German)
```

The package can also be installed (`pip install git+https://github.com/n4o-rse/wikibase-static`)
so that a site repository created from the template can use it without copying code.

## Licence and citation

MIT, see [`LICENSE`](LICENSE). Citation metadata is in [`CITATION.cff`](CITATION.cff).
