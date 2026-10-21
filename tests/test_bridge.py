"""Tests for the RDFS bridge of the kernel in the RDF export, and for recognising the kernel (S7b).

    python tests/test_bridge.py

The bridge (PRIMER.md, A4 "RDFS-Brücke") is written only when the kernel is part of the site. The tests build
a site from a few CSV rows with and without the kernel and read the exported Turtle back with rdflib.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "py"))

from wikibase_static import csvbuild, loader, rdf, step_rdf  # noqa: E402
from wikibase_static.model import Entity  # noqa: E402

RDFS, OWL, RDF = rdf.RDFS, rdf.OWL, rdf.RDF
BASE = "https://example.org"
EXPECTED = {
    (BASE + "/prop/direct/P1", RDFS + "subPropertyOf", RDFS + "subClassOf"),
    (BASE + "/prop/direct/P2", RDFS + "subPropertyOf", RDF + "type"),
    (BASE + "/prop/direct/P3", RDFS + "subPropertyOf", RDFS + "subPropertyOf"),
    (BASE + "/entity/Q1", OWL + "equivalentClass", RDFS + "Class"),
    (BASE + "/entity/Q2", OWL + "equivalentClass", RDF + "Property"),
    (BASE + "/entity/Q3", OWL + "equivalentClass", OWL + "Thing"),
}


def csv_site(kernel: bool) -> loader.Site:
    """A site from three CSV rows, through the same code as ``from-csv``, loaded as ``load`` loads it."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "csv").mkdir()
        (base / "csv" / "entities.csv").write_text(
            "id,kind,datatype,label_en\nQ100,class,,Thing\nQ101,item,,An item\nP100,property,string,note\n", encoding="utf-8")
        rows = "Q100,P1,Q3\nQ101,P2,Q100\n" if kernel else ""      # without the kernel there is no P1 and no P2
        (base / "csv" / "statements.csv").write_text(
            "subject,property,value\n" + rows + "Q101,P100,hello\n", encoding="utf-8")
        problems: list[str] = []
        site = csvbuild.read_set(base / "csv", problems, "csv")
        built = csvbuild.build(site, csvbuild.kernel_set() if kernel else None, BASE)
        assert not (problems or built.problems), (problems, built.problems)
        entities = base / "derived" / "entities"
        entities.mkdir(parents=True)
        for entity_id, obj in built.entities.items():
            (entities / f"{entity_id}.json").write_text(json.dumps(obj), encoding="utf-8")
        return loader.load_site(base / "none", base / "derived")


def export(site: loader.Site) -> rdf.Rdf:
    return rdf.build(site, rdf.Namespaces(BASE))


def as_strings(triples) -> set[tuple[str, str, str]]:
    return {(s.value, p.value, o.value) for s, p, o in triples if all(isinstance(x, rdf.Iri) for x in (s, p, o))}


class RecognisingTheKernel(unittest.TestCase):
    def test_a_site_with_the_kernel_has_it(self) -> None:
        self.assertTrue(csv_site(kernel=True).has_kernel())

    def test_a_site_without_the_kernel_does_not(self) -> None:
        self.assertFalse(csv_site(kernel=False).has_kernel())

    def test_a_harvested_wikibase_that_uses_the_same_numbers_does_not(self) -> None:
        site = loader.load_site(HERE / "fixtures", HERE / "none")
        self.assertTrue(site.entities, "the fixtures hold entities")
        self.assertFalse(site.has_kernel())

    def test_each_part_of_the_kernel_counts(self) -> None:
        for gone in ("Q1", "Q3", "P1", "P3"):
            site = csv_site(kernel=True)
            del site.entities[gone]
            self.assertFalse(site.has_kernel(), gone)

    def test_a_changed_class_tree_is_not_the_kernel(self) -> None:
        site = csv_site(kernel=True)
        site.entities["Q1"].statements = [s for s in site.entities["Q1"].statements if s.mainsnak.property != "P1"]
        self.assertFalse(site.has_kernel())


class TheBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.with_kernel = export(csv_site(kernel=True))
        cls.without = export(csv_site(kernel=False))

    def test_the_six_triples_are_there_with_the_kernel(self) -> None:
        self.assertEqual(as_strings(self.with_kernel.bridge), EXPECTED)
        self.assertTrue(self.with_kernel.bridge <= self.with_kernel.triples)

    def test_there_is_nothing_without_the_kernel(self) -> None:
        self.assertEqual(self.without.bridge, set())
        self.assertFalse(EXPECTED & as_strings(self.without.triples))

    def test_the_bridge_is_the_only_difference_in_the_triples_of_the_kernel_entities(self) -> None:
        rest = {t for t in self.with_kernel.triples if t not in self.with_kernel.bridge}
        self.assertTrue(rest <= self.with_kernel.triples)
        self.assertEqual(len(self.with_kernel.triples) - len(rest), 6)

    def test_each_triple_is_in_the_file_of_the_entity_it_is_about(self) -> None:
        for entity_id in ("Q1", "Q2", "Q3", "P1", "P2", "P3"):
            own = self.with_kernel.bridge & self.with_kernel.by_entity[entity_id]
            self.assertEqual(len(own), 1, entity_id)
        for entity_id in ("P4", "P10", "Q100", "Q101", "P100"):
            self.assertFalse(self.with_kernel.bridge & self.with_kernel.by_entity[entity_id], entity_id)

    def test_a_note_says_so(self) -> None:
        self.assertTrue(any("6 RDFS bridge triples" in n for n in self.with_kernel.notes))
        self.assertFalse(any("bridge" in n for n in self.without.notes))

    def test_the_turtle_file_has_a_section_of_its_own_and_reads_back_identically(self) -> None:
        import rdflib
        ns = rdf.Namespaces(BASE)
        text = rdf.to_turtle(self.with_kernel.triples, ns, "header", (rdf.BRIDGE_TITLE, self.with_kernel.bridge))
        head, _, tail = text.partition("# RDFS bridge of the kernel")
        self.assertTrue(tail, "the section comment is in the file")
        self.assertNotIn("owl:equivalentClass rdfs:Class", head)         # the bridge is not among the other blocks
        self.assertIn("owl:equivalentClass rdfs:Class", tail)
        self.assertIn("rdfs:subPropertyOf rdf:type", tail)               # rdf:type as an object, not "a"
        graph = rdflib.Graph()
        graph.parse(data=text, format="turtle")
        expected = rdflib.Graph()
        expected.parse(data=rdf.ntriples(self.with_kernel.triples), format="nt")
        self.assertTrue(graph.isomorphic(expected))
        self.assertEqual(len(graph), len(self.with_kernel.triples))

    def test_the_file_without_the_kernel_has_no_section(self) -> None:
        text = rdf.to_turtle(self.without.triples, rdf.Namespaces(BASE), "header")
        self.assertNotIn("RDFS bridge", text)
        self.assertEqual(text, rdf.to_turtle(self.without.triples, rdf.Namespaces(BASE), "header", (rdf.BRIDGE_TITLE, set())))


class TheStepWritesIt(unittest.TestCase):
    def test_the_published_file_of_a_kernel_entity_carries_its_triple(self) -> None:
        site = csv_site(kernel=True)
        result = export(site)
        ns = rdf.Namespaces(BASE)
        with tempfile.TemporaryDirectory() as tmp:
            from wikibase_static import utils
            docs = utils.DOCS
            utils.DOCS = Path(tmp)
            try:
                step_rdf.write_published(site, ns, result, "x", "example", ["RDF export of x, y", "b", "c"])
                p1 = (Path(tmp) / "ttl" / "P1.ttl").read_text(encoding="utf-8")
                q100 = (Path(tmp) / "ttl" / "Q100.ttl").read_text(encoding="utf-8")
            finally:
                utils.DOCS = docs
        self.assertIn("# RDFS bridge of the kernel", p1)
        self.assertIn("rdfs:subPropertyOf rdfs:subClassOf", p1)
        self.assertNotIn("RDFS bridge", q100)


if __name__ == "__main__":
    unittest.main()
