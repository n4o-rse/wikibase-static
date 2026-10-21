# wikibase-static

Static, read-only HTML demonstrators for Wikibase instances.

`wikibase-static` archives an existing Wikibase (for example one hosted on
Wikibase Cloud) through its public API, or builds a dummy Wikibase from CSV,
and publishes the result as a static site on GitHub Pages. The site looks and
navigates like a Wikibase: item and property pages, statements with qualifiers
and references, clickable Q- and P-ids, external links in a new tab, maps for
coordinates, Commons images, a search box and an in-browser SPARQL page. Nothing
on the published site can be edited.

> **Status.** `harvest` (S4), `load` (S2), the page renderer `build` (S3) and the search `search` (S5)
> work. The RDF export and SPARQL page (S6) and the CSV import (S7) are still skeleton steps that report
> "nothing to do". See [`PRIMER.md`](https://github.com/n4o-rse/wikibase-static/blob/main/PRIMER.md) (German) for the plan, the
> decisions taken so far and the order of the steps.

## Planned workflow

```
Wikibase (API)  --harvest-->  data/raw/      Wikibase JSON, unchanged, incremental
CSV             --from-csv->  data/derived/  the same format for a dummy Wikibase
                                  |
                                  +--build-->  docs/   static pages, search index, map
                                  +--rdf---->  dist/   RDF in the Wikibase data model
                                  +--sparql->  docs/   SPARQL page running in the browser
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

`build` renders the loaded entities into `docs/`: `index.html`, one flat page per entity (`Q123.html`,
`P1.html`) and `assets/`. It needs no network. The pages are laid out like a Wikibase: a sidebar with the
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
```

Offline tests (a fake Wikibase on localhost, no network needed):

```cmd
python -m unittest discover -s tests
```

The tests of the search box run the matching code of `search.js` under Node.js; where `node` is not on the
path they are skipped, and the other tests are unaffected.

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
                            site_config.py, templates/, static/ with app.js, search.js, map.js, style.css
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
