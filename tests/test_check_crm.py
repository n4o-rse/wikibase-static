"""Tests for S12: the DCAT -> CRM table, the spelled-out class tree, and the SHACL check of the CRM anchoring.

    python tests/test_check_crm.py

The check is compared with the rule of ``n4o-kg-profile`` (``crm_anchor`` in ``build/make_metadata.py``), re-stated here:
follow ``rdfs:subClassOf`` in the plain graph until the IRI starts with a CRM namespace.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))
sys.path.insert(0, str(HERE))

import rdflib  # noqa: E402
from rdflib import RDF, RDFS, URIRef  # noqa: E402

from test_crm import BASE, OVERLAY, csv_site  # noqa: E402
from wikibase_static import crm, rdf, step_check_crm  # noqa: E402

CRM_NS = ("http://www.cidoc-crm.org/cidoc-crm/", "http://www.cidoc-crm.org/extensions/")
E73 = "http://www.cidoc-crm.org/cidoc-crm/E73_Information_Object"
E31 = "http://www.cidoc-crm.org/cidoc-crm/E31_Document"
D1 = "http://www.cidoc-crm.org/extensions/crmdig/D1_Digital_Object"
INFO = rdf.CatalogInfo(title="Test", pages_url=BASE + "/", json_sizes={}, export_file="downloads/x.ttl",
                       ontology_file="downloads/wikibase-ontology.ttl", ontology_bytes=5)


def turtle(site, info=INFO) -> tuple[str, rdf.Rdf]:
    ns = rdf.Namespaces(BASE)
    result = rdf.build(site, ns, None, info)
    text = rdf.to_turtle(result.triples, ns, "", [(rdf.BRIDGE_TITLE, result.bridge), (rdf.CRM_TITLE, result.crm)])
    return text, result


def n4o_anchor(graph: rdflib.Graph, cls: URIRef, seen: set | None = None):
    seen = set() if seen is None else seen
    if cls in seen:
        return None
    seen.add(cls)
    if str(cls).startswith(CRM_NS):
        return cls
    for parent in graph.objects(cls, RDFS.subClassOf):
        if isinstance(parent, URIRef) and (found := n4o_anchor(graph, parent, seen)) is not None:
            return found
    return None


class Table(unittest.TestCase):
    def test_the_table_is_the_one_of_the_primer(self) -> None:
        table = crm.read_dcat_table()
        self.assertEqual(sorted(table), ["Catalog", "CatalogRecord", "DataService", "Dataset", "DatasetSeries", "Distribution", "Relationship", "Resource", "Role"])
        self.assertEqual(table["Resource"], (["crm:E1_CRM_Entity"], "fallback"))
        self.assertEqual(table["Dataset"][0], ["crm:E73_Information_Object"])
        self.assertEqual(table["DatasetSeries"][0], ["crm:E73_Information_Object"])
        self.assertEqual(table["Distribution"][0], ["crmdig:D1_Digital_Object"])
        self.assertEqual(table["Catalog"][0], ["crm:E31_Document", "crmdig:D1_Digital_Object"])
        self.assertEqual(table["CatalogRecord"][0], ["crm:E31_Document", "crmdig:D1_Digital_Object"])
        self.assertEqual(table["Role"][0], ["crm:E55_Type"])
        self.assertEqual(table["Relationship"], (["crm:E89_Propositional_Object"], "proposal"))
        self.assertEqual(table["DataService"], ([], "none"))

    def test_only_the_classes_in_use_are_aligned_and_an_extension_class_gets_its_chain(self) -> None:
        pairs = crm.dcat_alignment({crm.DCAT + "Dataset", crm.DCAT + "Catalog"})
        self.assertEqual(set(pairs), {(crm.DCAT + "Dataset", E73), (crm.DCAT + "Catalog", E31), (crm.DCAT + "Catalog", D1), (D1, E73)})
        self.assertEqual(crm.dcat_alignment({crm.DCAT + "DataService"}), [])


class Export(unittest.TestCase):
    def test_the_dcat_classes_of_the_export_are_tied_to_the_crm_with_or_without_an_overlay(self) -> None:
        for overlay in (None, OVERLAY):
            _text, result = turtle(csv_site(overlay))
            triples = {(s.value, p.value, o.value) for s, p, o in result.crm}
            for expected in ((crm.DCAT + "Dataset", RDFS.subClassOf, E73), (crm.DCAT + "Catalog", RDFS.subClassOf, E31), (crm.DCAT + "Distribution", RDFS.subClassOf, D1)):
                self.assertIn((str(expected[0]), str(expected[1]), expected[2]), triples)

    def test_without_dcat_there_is_no_alignment(self) -> None:
        _text, result = turtle(csv_site(None), None)
        self.assertEqual(result.crm, set())

    def test_subclass_of_and_instance_of_are_spelled_out_only_with_an_overlay(self) -> None:
        text, result = turtle(csv_site(OVERLAY))
        graph = rdflib.Graph()
        graph.parse(data=text, format="turtle")
        wd = lambda i: URIRef(f"{BASE}/entity/{i}")  # noqa: E731
        self.assertIn((wd("Q101"), RDFS.subClassOf, wd("Q100")), graph)
        self.assertIn((wd("Q102"), RDF.type, wd("Q101")), graph)
        self.assertNotIn((wd("Q100"), RDFS.subClassOf, wd("Q3")), graph)          # the kernel is not a class of the domain
        _text, plain = turtle(csv_site(None))
        self.assertFalse(any(p.value == RDFS.subClassOf and str(s.value).startswith(BASE + "/entity/Q10") for s, p, o in plain.triples
                             if isinstance(s, rdf.Iri) and isinstance(p, rdf.Iri)))

    def test_the_n4o_rule_reaches_a_crm_class_from_every_class_the_overlay_covers(self) -> None:
        text, _result = turtle(csv_site(OVERLAY))
        graph = rdflib.Graph()
        graph.parse(data=text, format="turtle")
        for class_id in ("Q100", "Q101"):
            self.assertEqual(str(n4o_anchor(graph, URIRef(f"{BASE}/entity/{class_id}"))), "http://www.cidoc-crm.org/extensions/crmdig/D14_Software")
        for name in ("Dataset", "Catalog", "Distribution"):
            self.assertIsNotNone(n4o_anchor(graph, URIRef(crm.DCAT + name)), name)
        self.assertIsNone(n4o_anchor(graph, URIRef(f"{BASE}/entity/Q103")))


class Check(unittest.TestCase):
    def rows(self, overlay: str | None):
        text, _result = turtle(csv_site(overlay))
        return step_check_crm.validate(text, BASE)

    def test_a_covered_tree_has_no_violation_and_the_loose_class_is_the_one_violation(self) -> None:
        rows = self.rows(OVERLAY)
        violations = [r for r in rows if r[0] == "Violation"]
        self.assertEqual([r[1] for r in violations], [f"{BASE}/entity/Q103"])
        self.assertIn("reaches no class of the CIDOC CRM", violations[0][2])

    def test_adding_the_missing_row_clears_it(self) -> None:
        self.assertEqual([r for r in self.rows(OVERLAY + "Q103,crm:E73,\n") if r[0] == "Violation"], [])

    def test_e1_alone_is_a_warning_and_no_violation(self) -> None:
        rows = self.rows(OVERLAY + "Q103,crm:E1,\n")
        self.assertEqual([r for r in rows if r[0] == "Violation"], [])
        warnings = [r for r in rows if r[0] == "Warning"]
        self.assertEqual([r[1] for r in warnings], [f"{BASE}/entity/Q103"])

    def test_a_dcat_class_without_a_crm_class_is_a_violation(self) -> None:
        text, _result = turtle(csv_site(OVERLAY + "Q103,crm:E73,\n"))
        text += f"\n<{BASE}/entity/Q102> a <{crm.DCAT}DataService> .\n"
        rows = step_check_crm.validate(text, BASE)
        self.assertEqual([(r[0], r[1]) for r in rows if r[0] == "Violation"], [("Violation", crm.DCAT + "DataService")])

    def test_the_kernel_classes_and_foreign_classes_are_not_checked(self) -> None:
        text, _result = turtle(csv_site(OVERLAY + "Q103,crm:E73,\n"))
        text += f"\n<{BASE}/entity/Q102> a <http://schema.org/Thing> .\n"
        self.assertEqual([r for r in step_check_crm.validate(text, BASE) if r[0] == "Violation"], [])


class Steps(unittest.TestCase):
    def test_check_crm_is_a_verb_and_not_part_of_the_default_run(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("wbs_main", HERE.parent / "main.py")
        main = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main)
        step = [s for s in main.STEPS if s[0] == "check-crm"]
        self.assertEqual(len(step), 1)
        self.assertFalse(step[0][2])


if __name__ == "__main__":
    unittest.main()
