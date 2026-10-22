"""Tests for ``import-open-archaeo`` (S7c): selection, rules, identity block, ids, reimport, hand rows.

    python tests/test_import_open_archaeo.py

Standard library only. Every test builds a small site (classes, properties with Wikidata twins, a mapping, a vocabulary and
a handful of open-archaeo entries) in a temporary folder and runs the step against it.
"""

from __future__ import annotations

import contextlib
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))

from wikibase_static import csvbuild, csvio, step_import_open_archaeo as imp  # noqa: E402

# local property -> (Wikidata twin, datatype); the numbers are the ones the demo has, a few of them
PROPS = {
    "P118": ("P6104", "wikibase-item"), "P122": ("P361", "wikibase-item"), "P106": ("P195", "wikibase-item"),
    "P116": ("P217", "string"), "P115": ("P2888", "url"), "P119": ("P2561", "monolingualtext"),
    "P117": ("P921", "wikibase-item"), "P113": ("P178", "wikibase-item"), "P146": ("P1545", "string"),
    "P123": ("P277", "wikibase-item"), "P109": ("P1547", "wikibase-item"), "P125": ("P1324", "url"),
    "P126": ("P8423", "wikibase-item"), "P105": ("P1065", "url"), "P104": ("P2960", "time"),
    "P108": ("P5565", "external-id"), "P124": ("P5568", "external-id"), "P114": ("P356", "external-id"),
    "P111": ("P1343", "wikibase-item"), "P120": ("P856", "url"), "P110": ("P973", "url"),
}
CLASSES = {"Q100": ("software", "Q7397", "Q3"), "Q101": ("research software", "Q95001953", "Q100"),
           "Q102": ("application software", "Q166142", "Q100"), "Q103": ("software library", "Q188860", "Q100"),
           "Q104": ("script file", "Q1070421", "Q100"), "Q106": ("chublet", "Q141115627", "Q101")}

COLUMNS = ["id", "slug", "url", "name", "description", "category", "platform", "platform_role", "tags", "authors",
           "repository", "repository_host", "registry", "registry_name", "doi", "publication", "website", "blogpost",
           "youtube", "twitter", "internetarchive", "notes"]


def entry(id_: str, slug: str, **kw: str) -> dict[str, str]:
    row = {c: "" for c in COLUMNS}
    row.update(id=id_, slug=slug, url=f"https://open-archaeo.info/post/{slug}/", name=slug.title(),
               description=f"{slug} does something.", category="Packages and libraries", tags="Statistical analysis",
               authors="alice")
    row.update(kw)
    return row


ENTRIES = [
    entry("a00001", "alpha", platform="R", platform_role="language", authors="alice|bob", tags="Seriation|Statistical analysis",
          repository="https://github.com/alice/alpha", repository_host="GitHub",
          internetarchive="https://archive.org/details/github.com-alice-alpha_-_2020-07-09_13-14-14",
          registry="https://CRAN.R-project.org/package=alpha/", registry_name="CRAN", doi="10.5281/zenodo.1",
          publication="https://doi.org/10.21105/joss.01821", website="https://alpha.example", blogpost="https://b.example/a",
          youtube="https://youtu.be/x", twitter="@alpha", notes="a note"),
    entry("b00002", "beta", category="Scripts", platform="QGIS", platform_role="host application",
          repository="https://bitbucket.org/b/beta", repository_host="Bitbucket"),
    entry("c00003", "gamma", category="Standalone software", platform="Mobile app", platform_role="deployment",
          repository="https://github.com/c/gamma|https://codeberg.org/c/gamma", repository_host="GitHub|Codeberg",
          internetarchive="https://archive.org/details/github.com-c-gamma-without-a-date"),
    entry("d00004", "delta", registry="https://pypi.org/project/delta/", registry_name="PyPI", tags="-"),
]

MAPPING = [
    ["(identity)", "P31|P6104|P361|P195", "", "identity", ""],
    ["id", "", "", "ignore", ""],
    ["slug", "P217", "P195", "slug", ""],
    ["url", "P2888", "", "string", ""],
    ["name", "", "", "label", ""],
    ["name", "P2561", "", "monolingual", ""],
    ["description", "", "", "description", ""],
    ["category", "P31", "", "class", ""],
    ["platform", "P277|P1547", "", "platform", ""],
    ["platform_role", "", "", "ignore", ""],
    ["tags", "P921", "", "items", ""],
    ["authors", "P178", "P1545", "persons", ""],
    ["repository", "P1324", "P8423|P1065|P2960", "repository", ""],
    ["repository_host", "", "", "ignore", ""],
    ["registry", "P5565|P5568", "", "registry", ""],
    ["registry_name", "", "", "ignore", ""],
    ["doi", "P356", "", "string", ""],
    ["publication", "P1343", "", "work", ""],
    ["website", "P856", "", "string", ""],
    ["blogpost", "P973", "", "string", ""],
    ["youtube", "P973", "", "string", ""],
    ["twitter", "", "", "ignore", ""],
    ["internetarchive", "", "", "ignore", ""],
    ["notes", "", "", "ignore", ""],
]
VOCABULARY = [
    ["identity", "chublet", "Q141115627", "chublet"], ["identity", "wikiproject", "Q141169143", "WikiProject chublets.software"],
    ["identity", "platform", "Q141115774", "chublets.software"], ["identity", "collection", "Q141190255", "open-archaeo (Repository)"],
    ["category", "Packages and libraries", "Q188860", ""], ["category", "Scripts", "Q1070421", ""],
    ["category", "Standalone software", "Q166142", ""], ["vcs", "Git", "Q186055", ""],
    ["language", "R", "", ""], ["host", "QGIS", "", ""], ["tag", "Seriation", "", ""], ["tag", "Statistical analysis", "Q12483", ""],
]


def write_csv(path: Path, columns: list[str], rows: list[list[str]] | list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row.get(c, "") for c in columns] if isinstance(row, dict) else row)
    path.write_text(out.getvalue(), encoding="utf-8", newline="")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_site(folder: Path, entries: list[dict[str, str]] | None = None, mapping=None, vocabulary=None) -> dict[str, Path]:
    """A site folder with the model, the mapping, the vocabulary and the input; returns the paths the step needs."""
    csv_dir = folder / "csv"
    ent = [{"id": i, "kind": "class", "origin": "starter-pack", "label_en": label} for i, (label, _w, _p) in CLASSES.items()]
    ent += [{"id": i, "kind": "property", "datatype": dt, "origin": "starter-pack", "label_en": f"property {i}"}
            for i, (_w, dt) in PROPS.items()]
    stm = []
    for i, (_label, wikidata, parent) in CLASSES.items():
        stm += [{"subject": i, "property": "P1", "value": parent, "origin": "starter-pack"},
                {"subject": i, "property": "P4", "value": wikidata, "origin": "starter-pack"}]
    for i, (wikidata, _dt) in PROPS.items():
        stm.append({"subject": i, "property": "P4", "value": wikidata, "origin": "starter-pack"})
    write_csv(csv_dir / "entities.csv", ["id", "kind", "datatype", "origin", "label_en"], ent)
    write_csv(csv_dir / "statements.csv", ["sid", "subject", "property", "value", "rank", "origin"], stm)
    write_csv(csv_dir / "qualifiers.csv", ["sid", "property", "value"], [])
    write_csv(csv_dir / "references.csv", ["sid", "group", "property", "value"], [])
    write_csv(csv_dir / "idmap.csv", ["source", "key", "id"],
              [["starter-pack", f"class:{w}", i] for i, (_l, w, _p) in CLASSES.items()])
    paths = {"csv": csv_dir, "mapping": csv_dir / "mapping" / "open-archaeo.csv",
             "vocabulary": csv_dir / "mapping" / "open-archaeo-vocabulary.csv", "input": folder / "raw" / "open-archaeo-software.csv"}
    write_csv(paths["mapping"], ["column", "property", "qualifiers", "rule", "note"], mapping or MAPPING)
    write_csv(paths["vocabulary"], ["section", "value", "wikidata", "label"], vocabulary or VOCABULARY)
    write_csv(paths["input"], COLUMNS, entries if entries is not None else ENTRIES)
    return paths


def run(paths: dict[str, Path], *extra: str) -> tuple[int, str]:
    args = ["--csv", str(paths["csv"]), "--input", str(paths["input"]), "--mapping", str(paths["mapping"]),
            "--vocabulary", str(paths["vocabulary"]), *extra]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = imp.main(args)
    return code, out.getvalue()


def problems_of(paths: dict[str, Path]) -> list[str]:
    """The model rules of from-csv (kernel, class tree, typed items) over the tables as they are now."""
    found: list[str] = []
    site = csvbuild.read_set(paths["csv"], found, "csv")
    return sorted(set(found) | set(csvbuild.build(site, csvbuild.kernel_set(), None).problems))


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.paths = build_site(self.folder)

    def table(self, name: str) -> list[dict[str, str]]:
        return read_csv(self.paths["csv"] / name)

    def snapshot(self) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in sorted(self.paths["csv"].glob("*.csv"))}

    def entity(self, label: str) -> str:
        return next(r["id"] for r in self.table("entities.csv") if r.get("label_en") == label)

    def values(self, subject: str, prop: str) -> list[str]:
        return [r["value"] for r in self.table("statements.csv") if r["subject"] == subject and r["property"] == prop]

    def sid(self, subject: str, prop: str, value: str) -> str:
        return next(r["sid"] for r in self.table("statements.csv")
                    if (r["subject"], r["property"], r["value"]) == (subject, prop, value))

    def qualifiers(self, sid: str) -> list[tuple[str, str]]:
        return [(r["property"], r["value"]) for r in self.table("qualifiers.csv") if r["sid"] == sid]


class Selection(unittest.TestCase):
    ROWS = [entry(f"{i:06x}", f"s{i}", category=("Packages and libraries" if i % 8 else "Scripts")) for i in range(416)]

    def test_it_takes_the_limit_in_proportion_to_the_categories(self) -> None:
        chosen = imp.select(self.ROWS, 100)
        self.assertEqual(len(chosen), 100)
        sizes = {c: sum(1 for r in self.ROWS if r["category"] == c) for c in ("Packages and libraries", "Scripts")}
        for category, size in sizes.items():
            count = sum(1 for r in chosen if r["category"] == category)
            self.assertAlmostEqual(count, 100 * size / 416, delta=1, msg=category)

    def test_it_is_deterministic_and_independent_of_the_input_order(self) -> None:
        first = [r["id"] for r in imp.select(self.ROWS, 100)]
        self.assertEqual(first, [r["id"] for r in imp.select(list(reversed(self.ROWS)), 100)])
        self.assertEqual(first, sorted(first))

    def test_a_limit_at_least_the_size_takes_all_and_none_means_all(self) -> None:
        self.assertEqual(len(imp.select(self.ROWS, 416)), 416)
        self.assertEqual(len(imp.select(self.ROWS, 9999)), 416)
        self.assertEqual(len(imp.select(self.ROWS, None)), 416)

    def test_a_small_limit_still_adds_up(self) -> None:
        for limit in (1, 2, 7, 33):
            self.assertEqual(len(imp.select(self.ROWS, limit)), limit)


class Rules(Case):
    def setUp(self) -> None:
        super().setUp()
        self.code, self.report = run(self.paths, "--all")
        self.alpha = self.entity("Alpha")

    def test_it_runs_and_the_model_has_no_problem(self) -> None:
        self.assertEqual(self.code, 0, self.report)
        self.assertNotIn("WARN", self.report)
        self.assertEqual(problems_of(self.paths), [])

    def test_the_identity_block_is_variant_v2(self) -> None:
        wikiproject, platform, collection = (self.entity(x) for x in
                                             ("WikiProject chublets.software", "chublets.software", "open-archaeo (Repository)"))
        for label in ("Alpha", "Beta", "Gamma", "Delta"):
            item = self.entity(label)
            self.assertIn("Q106", self.values(item, "P2"), label)                 # instance of chublet
            self.assertEqual(self.values(item, "P118"), [wikiproject], label)
            self.assertEqual(self.values(item, "P122"), [platform, collection], label)
            self.assertEqual(self.values(item, "P106"), [collection], label)
            self.assertEqual(self.values(item, "P116"), [label.lower()], label)
            self.assertEqual(self.qualifiers(self.sid(item, "P116", label.lower())), [("P106", collection)])
            self.assertEqual(self.values(item, "P115"), [f"https://open-archaeo.info/post/{label.lower()}/"], label)

    def test_the_identity_items_have_their_twins_and_a_class(self) -> None:
        for label, wikidata in (("WikiProject chublets.software", "Q141169143"), ("chublets.software", "Q141115774"),
                                ("open-archaeo (Repository)", "Q141190255")):
            item = self.entity(label)
            self.assertEqual(self.values(item, "P4"), [wikidata])
            self.assertEqual(self.values(item, "P2"), ["Q3"])

    def test_the_category_gives_the_class_of_the_vocabulary(self) -> None:
        self.assertEqual(self.values(self.alpha, "P2"), ["Q106", "Q103"])
        self.assertEqual(self.values(self.entity("Beta"), "P2"), ["Q106", "Q104"])
        self.assertEqual(self.values(self.entity("Gamma"), "P2"), ["Q106", "Q102"])

    def test_name_and_description_become_label_and_description_and_the_name_a_statement(self) -> None:
        row = next(r for r in self.table("entities.csv") if r["id"] == self.alpha)
        self.assertEqual((row["label_en"], row["description_en"], row["origin"]), ("Alpha", "alpha does something.", "open-archaeo"))
        self.assertEqual(self.values(self.alpha, "P119"), ["en:Alpha"])

    def test_authors_keep_their_order_as_the_series_ordinal(self) -> None:
        authors = self.values(self.alpha, "P113")
        self.assertEqual([r["label_en"] for a in authors for r in self.table("entities.csv") if r["id"] == a], ["alice", "bob"])
        ordinals = [self.qualifiers(self.sid(self.alpha, "P113", a)) for a in authors]
        self.assertEqual(ordinals, [[("P146", "1")], [("P146", "2")]])
        self.assertEqual(self.values(self.entity("Beta"), "P113"), [authors[0]])        # one person item per name

    def test_tags_become_items_with_a_twin_only_where_the_vocabulary_has_one(self) -> None:
        tags = self.values(self.alpha, "P117")
        self.assertEqual(len(tags), 2)
        seriation, statistical = self.entity("Seriation"), self.entity("Statistical analysis")
        self.assertEqual(tags, [seriation, statistical])
        self.assertEqual(self.values(seriation, "P4"), [])
        self.assertEqual(self.values(statistical, "P4"), ["Q12483"])
        self.assertEqual(self.values(seriation, "P2"), ["Q3"])

    def test_a_tag_that_is_not_in_the_vocabulary_still_becomes_an_item(self) -> None:
        self.assertEqual(self.values(self.entity("Delta"), "P117"), [self.entity("-")])

    def test_platform_follows_the_role(self) -> None:
        self.assertEqual([r["label_en"] for v in self.values(self.alpha, "P123") for r in self.table("entities.csv") if r["id"] == v], ["R"])
        self.assertEqual(self.values(self.alpha, "P109"), [])
        beta = self.entity("Beta")
        self.assertEqual([r["label_en"] for v in self.values(beta, "P109") for r in self.table("entities.csv") if r["id"] == v], ["QGIS"])
        self.assertEqual(self.values(self.entity("Gamma"), "P123") + self.values(self.entity("Gamma"), "P109"), [])

    def test_the_deployment_role_is_reported_not_imported(self) -> None:
        self.assertIn("not imported (1x): platform with the role deployment", self.report)

    def test_the_repository_carries_its_qualifiers(self) -> None:
        git = self.entity("Git")
        self.assertEqual(self.values(self.entity("Git"), "P4"), ["Q186055"])
        sid = self.sid(self.alpha, "P125", "https://github.com/alice/alpha")
        self.assertEqual(self.qualifiers(sid), [
            ("P126", git),
            ("P105", "https://archive.org/details/github.com-alice-alpha_-_2020-07-09_13-14-14"),
            ("P104", "2020-07-09")])

    def test_two_repositories_pair_with_their_hosts_and_only_the_first_gets_the_archive(self) -> None:
        gamma, git = self.entity("Gamma"), self.entity("Git")
        first, second = self.values(gamma, "P125")
        self.assertEqual(self.qualifiers(self.sid(gamma, "P125", first)),
                         [("P126", git), ("P105", "https://archive.org/details/github.com-c-gamma-without-a-date")])
        self.assertEqual(self.qualifiers(self.sid(gamma, "P125", second)), [("P126", git)])
        self.assertIn("no archive date", self.report)

    def test_a_host_that_is_not_certainly_git_gets_no_version_control_system(self) -> None:
        beta = self.entity("Beta")
        self.assertEqual(self.qualifiers(self.sid(beta, "P125", "https://bitbucket.org/b/beta")), [])
        self.assertIn("repository host 'Bitbucket'", self.report)

    def test_the_registry_package_name_is_read_from_the_url(self) -> None:
        self.assertEqual(self.values(self.alpha, "P108"), ["alpha"])
        self.assertEqual(self.values(self.entity("Delta"), "P124"), ["delta"])
        self.assertEqual(self.values(self.alpha, "P124"), [])

    def test_strings_and_urls_are_taken_as_they_are(self) -> None:
        self.assertEqual(self.values(self.alpha, "P114"), ["10.5281/zenodo.1"])
        self.assertEqual(self.values(self.alpha, "P120"), ["https://alpha.example"])
        self.assertEqual(sorted(self.values(self.alpha, "P110")), ["https://b.example/a", "https://youtu.be/x"])

    def test_a_publication_is_an_item_labelled_with_its_doi(self) -> None:
        work = self.entity("10.21105/joss.01821")
        self.assertEqual(self.values(self.alpha, "P111"), [work])
        self.assertEqual(self.values(work, "P2"), ["Q3"])

    def test_columns_that_are_not_data_are_left_out(self) -> None:
        for value in ("@alpha", "a note"):
            self.assertFalse(any(value in r["value"] for r in self.table("statements.csv")), value)

    def test_every_statement_has_one_reference_to_the_entry_page(self) -> None:
        own = [r for r in self.table("statements.csv") if r["origin"] == "open-archaeo"]
        references = self.table("references.csv")
        self.assertTrue(own)
        for row in own:
            refs = [r for r in references if r["sid"] == row["sid"]]
            self.assertEqual(len(refs), 1, row)
            self.assertEqual((refs[0]["group"], refs[0]["property"]), ("1", "P6"))
            self.assertTrue(refs[0]["value"].startswith("https://open-archaeo.info/post/"), refs[0])

    def test_the_reference_of_a_shared_item_is_the_first_entry_that_named_it(self) -> None:
        alice = self.entity("alice")
        sid = self.sid(alice, "P2", "Q3")
        self.assertEqual([r["value"] for r in self.table("references.csv") if r["sid"] == sid],
                         ["https://open-archaeo.info/post/alpha/"])

    def test_the_report_says_how_much_was_imported(self) -> None:
        self.assertIn("4 entries", self.report)
        self.assertIn("4 selected", self.report)
        self.assertIn("items: 4 software", self.report)


class Reimport(Case):
    def test_a_second_run_writes_nothing(self) -> None:
        run(self.paths, "--all")
        before = self.snapshot()
        code, report = run(self.paths, "--all")
        self.assertEqual(code, 0)
        self.assertIn("0 file(s) written", report)
        self.assertEqual(self.snapshot(), before)

    def test_the_tables_are_canonical_after_an_import(self) -> None:
        run(self.paths, "--all")
        tables = {n: csvio.read_table(self.paths["csv"] / n, [], [], n) for n in csvio.TABLES}
        for name, text in csvio.canonical_texts(tables).items():
            self.assertEqual((self.paths["csv"] / name).read_text(encoding="utf-8"), text, name)

    def test_dry_run_writes_nothing(self) -> None:
        before = self.snapshot()
        code, report = run(self.paths, "--all", "--dry-run")
        self.assertEqual((code, self.snapshot()), (0, before))
        self.assertIn("would change", report)

    def test_a_value_changed_by_hand_with_the_origin_emptied_survives(self) -> None:
        run(self.paths, "--all")
        alpha = self.entity("Alpha")
        rows = self.table("statements.csv")
        for row in rows:
            if row["subject"] == alpha and row["property"] == "P120":
                row["value"], row["origin"] = "https://hand.example", ""
        write_csv(self.paths["csv"] / "statements.csv", ["sid", "subject", "property", "value", "rank", "origin"], rows)
        _code, report = run(self.paths, "--all")
        self.assertEqual(self.values(alpha, "P120"), ["https://hand.example"])
        self.assertIn("hand rows protect 1 (1 not written, 0 kept)", report)
        run(self.paths, "--all")
        self.assertEqual(self.values(alpha, "P120"), ["https://hand.example"])

    def test_the_hand_row_protects_its_property_but_not_the_rest_of_the_subject(self) -> None:
        run(self.paths, "--all")
        alpha, rows = self.entity("Alpha"), self.table("statements.csv")
        for row in rows:
            if row["subject"] == alpha and row["property"] == "P117":
                row["origin"] = ""
                break
        write_csv(self.paths["csv"] / "statements.csv", ["sid", "subject", "property", "value", "rank", "origin"], rows)
        before = self.values(alpha, "P117")
        write_csv(self.paths["input"], COLUMNS, [dict(e, tags="Other") if e["id"] == "a00001" else e for e in ENTRIES])
        run(self.paths, "--all")
        self.assertEqual(self.values(alpha, "P117"), before)                      # all rows of that property stay
        self.assertEqual(self.values(alpha, "P115"), ["https://open-archaeo.info/post/alpha/"])

    def test_an_importer_row_follows_a_change_in_the_source(self) -> None:
        run(self.paths, "--all")
        write_csv(self.paths["input"], COLUMNS, [dict(e, website="https://new.example") if e["id"] == "a00001" else e for e in ENTRIES])
        run(self.paths, "--all")
        self.assertEqual(self.values(self.entity("Alpha"), "P120"), ["https://new.example"])

    def test_a_row_of_someone_else_is_never_touched(self) -> None:
        def others() -> list[tuple[str, ...]]:
            return sorted(tuple(r.values()) for r in self.table("statements.csv") if r["origin"] == "starter-pack")

        before = others()
        run(self.paths, "--all")
        self.assertEqual(others(), before)

    def test_an_entity_row_with_the_origin_emptied_wins(self) -> None:
        run(self.paths, "--all")
        rows = self.table("entities.csv")
        for row in rows:
            if row["label_en"] == "Alpha":
                row["label_en"], row["origin"] = "Alpha (by hand)", ""
        write_csv(self.paths["csv"] / "entities.csv", ["id", "kind", "datatype", "origin", "label_en", "description_en"], rows)
        run(self.paths, "--all")
        labels = [r["label_en"] for r in self.table("entities.csv")]
        self.assertIn("Alpha (by hand)", labels)
        self.assertNotIn("Alpha", labels)                                     # no second row for the same id

    def test_the_selection_can_shrink_and_what_is_gone_is_removed(self) -> None:
        run(self.paths, "--all")
        _code, _report = run(self.paths, "--limit", "1")
        labels = [r["label_en"] for r in self.table("entities.csv") if r["origin"] == "open-archaeo"]
        self.assertIn("Alpha", labels)
        self.assertNotIn("Delta", labels)
        self.assertEqual(problems_of(self.paths), [])


class Ids(Case):
    def test_an_id_is_never_used_twice_even_after_an_entry_is_gone(self) -> None:
        run(self.paths, "--all")
        ids = {r["key"]: r["id"] for r in self.table("idmap.csv") if r["source"] == "open-archaeo"}
        self.assertEqual(ids["entry:a00001"], "Q107")                      # the next free number after the pack's Q106
        run(self.paths, "--limit", "1")
        write_csv(self.paths["input"], COLUMNS, ENTRIES + [entry("e00005", "epsilon")])
        run(self.paths, "--all")
        after = {r["key"]: r["id"] for r in self.table("idmap.csv") if r["source"] == "open-archaeo"}
        self.assertEqual({k: v for k, v in after.items() if k in ids}, ids)  # the old keys keep their ids
        new = [v for k, v in after.items() if k not in ids]
        self.assertTrue(new)
        self.assertGreater(min(int(v[1:]) for v in new), max(int(v[1:]) for v in ids.values()))

    def test_the_numbers_of_the_pack_are_not_taken(self) -> None:
        run(self.paths, "--all")
        taken = [r["id"] for r in self.table("idmap.csv") if r["source"] == "starter-pack"]
        mine = [r["id"] for r in self.table("idmap.csv") if r["source"] == "open-archaeo"]
        self.assertFalse(set(taken) & set(mine))
        self.assertEqual(len(mine), len(set(mine)))

    def test_the_same_input_gives_the_same_ids_in_a_fresh_site(self) -> None:
        run(self.paths, "--all")
        with tempfile.TemporaryDirectory() as other:
            paths = build_site(Path(other))
            run(paths, "--all")
            self.assertEqual((paths["csv"] / "idmap.csv").read_bytes(), (self.paths["csv"] / "idmap.csv").read_bytes())


class Problems(Case):
    def test_a_property_without_a_local_twin_is_a_warning_and_writes_nothing_for_it(self) -> None:
        rows = [r for r in MAPPING if r[1] != "P856"] + [["website", "P9999", "", "string", ""]]
        write_csv(self.paths["mapping"], ["column", "property", "qualifiers", "rule", "note"], rows)
        code, report = run(self.paths, "--all")
        self.assertEqual(code, 0)
        self.assertIn("WARN: [import-open-archaeo] mapping: the Wikidata property P9999 has no local twin", report)
        self.assertEqual(self.values(self.entity("Alpha"), "P120"), [])

    def test_an_unknown_rule_is_an_error_with_the_line(self) -> None:
        write_csv(self.paths["mapping"], ["column", "property", "qualifiers", "rule", "note"], MAPPING + [["x", "", "", "teleport", ""]])
        code, report = run(self.paths, "--all")
        self.assertEqual(code, 2)
        self.assertIn("open-archaeo.csv:26: unknown rule 'teleport'", report)

    def test_a_missing_file_is_an_error(self) -> None:
        self.paths["input"].unlink()
        code, report = run(self.paths, "--all")
        self.assertEqual(code, 2)
        self.assertIn("input:", report)

    def test_a_vocabulary_without_the_identity_rows_is_an_error(self) -> None:
        write_csv(self.paths["vocabulary"], ["section", "value", "wikidata", "label"], [r for r in VOCABULARY if r[1] != "wikiproject"])
        code, report = run(self.paths, "--all")
        self.assertEqual(code, 2)
        self.assertIn("no identity row for 'wikiproject'", report)

    def test_a_category_without_a_class_is_reported_not_guessed(self) -> None:
        write_csv(self.paths["vocabulary"], ["section", "value", "wikidata", "label"], [r for r in VOCABULARY if r[1] != "Scripts"])
        _code, report = run(self.paths, "--all")
        self.assertIn("category 'Scripts': no local class", report)
        self.assertEqual(self.values(self.entity("Beta"), "P2"), ["Q106"])


if __name__ == "__main__":
    unittest.main()
