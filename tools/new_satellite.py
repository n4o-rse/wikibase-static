#!/usr/bin/env python3
"""Make the skeleton of a new satellite site: a static Wikibase of a set of Wikidata items, or a static copy of a Wikibase.

    python tools/new_satellite.py wd-irishroundtowers-static --title "Irish Round Towers (static Wikibase)" \\
        --description "A static, read-only Wikibase of the Irish round towers." --prefix irt \\
        --query data/seeds/wikidata-roundtowers.rq --logo logo.png --out ../wd-irishroundtowers-static

    python tools/new_satellite.py wb-squirrelbase-static --title "squirrelbase (static copy)" \\
        --description "Static, read-only copy of squirrelbase." --prefix sqb \\
        --wikibase https://squirrelbase.wikibase.cloud --out ../wb-squirrelbase-static

``tools/satellite-template/`` is the skeleton of a Wikidata satellite (the wrapper ``main.py`` that starts ``import-wikidata`` with
``--generic --provenance item``, the two workflows, ``site.yaml``, README, PRIMER, empty CSV tables); with ``--wikibase URL``
``tools/satellite-template-wikibase/`` is used instead (the wrapper has the verbs ``harvest`` and ``fetch-logo``; the data come
from the harvest, so there are no seeds and no CSV tables). This script fills in the name, the title, the prefix and the date,
copies the seed query (``--query``, repeatable) and the logo, and writes the folder. Nothing is built: the first run does that
(the line is printed at the end), because the site needs its data before it can be built.

Settings that follow the size of the set: ``--small`` keeps ``entity_files: true`` and ``browser_graph: full`` (a set of up to
a few hundred items); the default is ``entity_files: false`` and ``browser_graph: slim``.

Standard library only. The output is a function of the arguments and the date (``--date`` to fix it).
"""

from __future__ import annotations

import argparse
import datetime
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "satellite-template"
TEMPLATE_WIKIBASE = HERE / "satellite-template-wikibase"
SOURCE_URL = re.compile(r"^https?://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]+)?(/[^\s?#]*)?$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PREFIX = re.compile(r"^[a-z][a-z0-9]{0,11}$")
RESERVED = {"wd", "wdt", "wds", "wdv", "wdref", "wdno", "wikibase", "rdf", "rdfs", "owl", "skos", "schema", "prov", "dcat", "dcterms",
            "geo", "xsd", "p", "ps", "pq", "pr", "bd", "cc", "sh"}
ORG = "n4o-rse"


def package_version() -> str:
    text = (HERE.parent / "py" / "wikibase_static" / "__init__.py").read_text(encoding="utf-8")
    found = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not found:
        raise SystemExit("cannot read __version__ of the package")
    return found.group(1)


def render(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    left = re.findall(r"\{\{[a-z_]+\}\}", text)
    if left:
        raise SystemExit(f"unfilled placeholder in the template: {sorted(set(left))}")
    return text


def siblings(lines: list[str], slug: str) -> str:
    out = []
    for line in lines:
        name = line.strip().split("/")[-1]
        if name and name != slug:
            out.append(f"- [`{line.strip()}`](https://github.com/{line.strip()}): a sibling site.")
    return "\n".join(out)


def copy_template(template: Path, out: Path, values: dict[str, str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for source in sorted(template.rglob("*")):
        if source.is_dir():
            continue
        target = out / source.relative_to(template)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        if source.suffix in {".md", ".yaml", ".yml", ".cff", ".txt", ".py", ".cmd", ""} or source.name in {"LICENSE", ".gitignore", ".gitattributes"}:
            text = data.decode("utf-8")
            if "{{" in text:
                text = render(text, values)
            data = text.encode("utf-8")
        target.write_bytes(data)


def make_wikibase(args: argparse.Namespace, source_url: str, version: str) -> int:
    """The skeleton of a static copy of a Wikibase (``--wikibase``)."""
    if args.logo and not args.logo.is_file():
        raise SystemExit(f"--logo {args.logo}: no such file")
    host = re.sub(r"^https?://", "", source_url).split("/")[0]
    values = {
        "slug": args.slug, "title": args.title, "description": args.description.strip(), "prefix": args.prefix,
        "version": version, "today": args.date, "source_url": source_url, "host": host,
        "logo_line": "logo: assets/logo.png" if args.logo else "# logo: assets/logo.png",
        "siblings": siblings([s for s in args.siblings.split(",") if s.strip()], args.slug),
    }
    copy_template(TEMPLATE_WIKIBASE, args.out, values)
    if args.logo:
        (args.out / "assets").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.logo, args.out / "assets" / "logo.png")
    print(f"{args.out}: skeleton of {args.slug} (wikibase-static {version}), a static copy of {source_url}")
    print("Once per repository, before the first push: Settings -> Pages -> Source: GitHub Actions.")
    print("First run (one line, Windows cmd, in the folder; --probe tests the host first):")
    steps = ["pip install -r requirements.txt", "python main.py harvest --probe", "python main.py harvest"]
    if not args.logo:
        steps.append("python main.py fetch-logo")
    steps += ["python main.py --strict", "git add -A", 'git commit -m "S0: first harvest"', "git push"]
    print(" && ".join(steps))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="new_satellite.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("slug", help="repository name, e.g. wd-irishroundtowers-static")
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", required=True, help="one or two sentences, English")
    parser.add_argument("--prefix", required=True, help="the prefix family of the RDF export (3 to 5 letters), e.g. irt")
    parser.add_argument("--wikibase", metavar="URL", help="a static copy of this Wikibase (harvested) instead of a set of Wikidata items, "
                                                          "e.g. https://squirrelbase.wikibase.cloud; no --query, --qids or --small then")
    parser.add_argument("--query", action="append", default=[], type=Path, metavar="FILE",
                        help="a seed query (SELECT ... ?item [?kind]); copied to data/seeds/wikidata-<name>.rq; repeatable")
    parser.add_argument("--qids", default="", help="single seeds, comma separated (Q1,Q2); they are added to data/seeds/wikidata-qids.txt")
    parser.add_argument("--seeds-text", default="", help="how the items are found, for the README and the PRIMER")
    parser.add_argument("--logo", type=Path, help="a PNG for the pages (copied to assets/logo.png)")
    parser.add_argument("--small", action="store_true", help="a set of up to a few hundred items: a Turtle and JSON file per item, full browser graph")
    parser.add_argument("--siblings", default="", help="other sites of the family, owner/repo comma separated (README)")
    parser.add_argument("--out", type=Path, required=True, help="the folder to write (must not exist or be empty)")
    parser.add_argument("--date", default=datetime.date.today().isoformat(), help="data_as_of and the PRIMER date (YYYY-MM-DD)")
    args = parser.parse_args(argv)

    if not SLUG.match(args.slug):
        parser.error("slug: lower-case letters, digits and hyphens")
    if not PREFIX.match(args.prefix) or args.prefix in RESERVED:
        parser.error("prefix: a short lower-case name (letters and digits, at most 12, starting with a letter) that is not a vocabulary prefix")
    wikibase = args.wikibase.rstrip("/") if args.wikibase else None
    if wikibase:
        if args.query or args.qids or args.seeds_text or args.small:
            parser.error("--wikibase makes a copy of a Wikibase: --query, --qids, --seeds-text and --small belong to a Wikidata satellite")
        if not SOURCE_URL.match(wikibase):
            parser.error("--wikibase: an http(s) address such as https://squirrelbase.wikibase.cloud")
    elif not args.query and not args.qids:
        parser.error("give at least one --query or --qids (or --wikibase URL): a site without seeds has nothing in it")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.date):
        parser.error("--date: YYYY-MM-DD")
    names = []
    for query in args.query:
        if not query.is_file():
            parser.error(f"--query {query}: no such file")
        name = re.sub(r"^wikidata-", "", query.stem)
        if not re.match(r"^[a-z0-9][a-z0-9-]*$", name):
            parser.error(f"--query {query}: the name after 'wikidata-' must be lower-case letters, digits and hyphens")
        names.append((name, query))
    qids = [q.strip() for q in args.qids.split(",") if q.strip()]
    for q in qids:
        if not re.match(r"^Q[1-9][0-9]*$", q):
            parser.error(f"--qids: {q!r} is not an item id")
    if args.out.exists() and any(args.out.iterdir()):
        parser.error(f"{args.out} exists and is not empty")

    version = package_version()
    if wikibase:
        return make_wikibase(args, wikibase, version)
    entity_files, browser_graph = ("true", "full") if args.small else ("false", "slim")
    seed_text = args.seeds_text or ("the result of " + ", ".join(f"`data/seeds/wikidata-{n}.rq`" for n, _ in names)
                                    + (" and single items listed in `data/seeds/wikidata-qids.txt`" if qids else "")
                                    if names else "single items listed in `data/seeds/wikidata-qids.txt`")
    values = {
        "slug": args.slug, "title": args.title, "description": args.description.strip(), "prefix": args.prefix,
        "version": version, "today": args.date, "entity_files": entity_files, "browser_graph": browser_graph,
        "logo_line": ("# The logo: copied into docs/assets/logo/.\nlogo: assets/logo.png" if args.logo else "# No logo yet: put a PNG at assets/logo.png and name it here (logo: assets/logo.png)."),
        "seed_text": seed_text,
        "siblings": siblings([s for s in args.siblings.split(",") if s.strip()], args.slug),
    }

    args.out.mkdir(parents=True, exist_ok=True)
    for source in sorted(TEMPLATE.rglob("*")):
        if source.is_dir():
            continue
        target = args.out / source.relative_to(TEMPLATE)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        if source.suffix in {".md", ".yaml", ".yml", ".cff", ".txt", ".py", ".cmd", ""} or source.name in {"LICENSE", ".gitignore", ".gitattributes"}:
            text = data.decode("utf-8")
            if "{{" in text:
                text = render(text, values)
            data = text.encode("utf-8")
        target.write_bytes(data)
    if qids:
        listing = args.out / "data" / "seeds" / "wikidata-qids.txt"
        listing.write_text(listing.read_text(encoding="utf-8") + "".join(f"{q}\n" for q in qids), encoding="utf-8")
    for name, query in names:
        shutil.copyfile(query, args.out / "data" / "seeds" / f"wikidata-{name}.rq")
    if args.logo:
        if not args.logo.is_file():
            parser.error(f"--logo {args.logo}: no such file")
        (args.out / "assets").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.logo, args.out / "assets" / "logo.png")

    print(f"{args.out}: skeleton of {args.slug} (wikibase-static {version}), {len(names)} seed query file(s), {len(qids)} single seed(s)")
    print("Once per repository, before the first push: Settings -> Pages -> Source: GitHub Actions.")
    print("First run (one line, Windows cmd, in the folder):")
    print('pip install -r requirements.txt && python main.py seeds-from-sparql && python main.py import-wikidata && python main.py --strict '
          '&& git add -A && git commit -m "S0: first import from Wikidata" && git push')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
