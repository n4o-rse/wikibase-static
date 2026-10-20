# wikibase-static

Static, read-only HTML demonstrators for Wikibase instances.

`wikibase-static` archives an existing Wikibase (for example one hosted on
Wikibase Cloud) through its public API, or builds a dummy Wikibase from CSV,
and publishes the result as a static site on GitHub Pages. The site looks and
navigates like a Wikibase: item and property pages, statements with qualifiers
and references, clickable Q- and P-ids, external links in a new tab, maps for
coordinates, Commons images, a search box and an in-browser SPARQL page. Nothing
on the published site can be edited.

> **Status: skeleton.** The repository currently holds the orchestrator, the
> package layout and the work plan. Every step reports "nothing to do" until it
> is implemented; see [`PRIMER.md`](PRIMER.md) (German) for the plan, the
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

Python 3.10 or later; the skeleton needs no third-party packages.

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

Offline tests (a fake Wikibase on localhost, no network needed):

```cmd
python tests\test_harvest.py
python tests\test_loader.py
```

## Layout

```
main.py                     the only entry point
py/wikibase_static/         the package (one module per step, utils.py, model.py, loader.py)
data/raw/                   harvested JSON, as obtained
data/derived/               intermediates made from CSV
dist/                       versioned products: RDF, pipeline report
docs/                       the site, served by GitHub Pages
PRIMER.md                   work plan and decisions (German)
```

The package can also be installed (`pip install git+https://github.com/n4o-rse/wikibase-static`)
so that a site repository created from the template can use it without copying code.

## Licence and citation

MIT, see [`LICENSE`](LICENSE). Citation metadata is in [`CITATION.cff`](CITATION.cff).
