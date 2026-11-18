"""Tests for the CIDOC CRM overlay (S11): reading ``data/crm.csv``, inheritance, the RDF section, the page and the query.

    python tests/test_crm.py

PRIMER.md, A4 "CRM-Overlay" and "Erlaubte CRM-Familien". The site is built from a few CSV rows through the same code
as ``from-csv`` and loaded as ``load`` loads it.
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
sys.path.insert(0, str(HERE))

import test_build  # noqa: E402
from wikibase_static import crm, csvbuild, loader, rdf, sparql, step_rdf  # noqa: E402

BASE = "https://example.org"
RDFS = rdf.RDFS
D14 = "http://www.cidoc-crm.org/extensions/crmdig/D14_Software"
D1 = "http://www.cidoc-crm.org/extensions/crmdig/D1_Digital_Object"
E73 = "http://www.cidoc-crm.org/cidoc-crm/E73_Information_Object"
CLASSES = "id,kind,datatype,label_en\nQ100,class,,software\nQ101,class,,library\nQ102,item,,Numpy\nQ103,class,,loose class\nP100,property,string,note\n"
STATEMENTS = "subject,property,value\nQ100,P1,Q3\nQ101,P1,Q100\nQ102,P2,Q101\nQ103,P1,Q3\nQ102,P100,hello\n"


def csv_site(overlay: str | None) -> loader.Site:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "csv").mkdir()
        (base / "csv" / "entities.csv").write_text(CLASSES, encoding="utf-8")
        (base / "csv" / "statements.csv").write_text(STATEMENTS, encoding="utf-8")
        problems: list[str] = []
        site = csvbuild.read_set(base / "csv", problems, "csv")
        built = csvbuild.build(site, csvbuild.kernel_set(), BASE)
        assert not (problems or built.problems), (problems, built.problems)
        entities = base / "derived" / "entities"
        entities.mkdir(parents=True)
        for entity_id, obj in built.entities.items():
            (entities / f"{entity_id}.json").write_text(json.dumps(obj), encoding="utf-8")
        if overlay is not None:
            (base / "crm.csv").write_text(overlay, encoding="utf-8")
        return loader.load_site(base / "none", base / "derived")


OVERLAY = "class,crm_class,note\nQ100,crmdig:D14,software\n"


class Reading(unittest.TestCase):
    def read(self, text: str, known: set[str] | None = None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crm.csv"
            path.write_text(text, encoding="utf-8")
            return crm.read_overlay(path, known)

    def test_a_missing_file_is_no_overlay_and_no_problem(self) -> None:
        self.assertEqual(crm.read_overlay(Path("does-not-exist.csv")), ({}, []))

    def test_a_short_code_is_written_out_and_the_order_of_the_file_is_kept(self) -> None:
        overlay, problems = self.read("class,crm_class,note\nQ100,crmdig:D14,\nQ100,crm:E73,\nQ101,crm:E22_Human-Made_Object,\n")
        self.assertEqual(problems, [])
        self.assertEqual(overlay, {"Q100": ["crmdig:D14_Software", "crm:E73_Information_Object"], "Q101": ["crm:E22_Human-Made_Object"]})

    def test_unknown_family_bad_id_unknown_entity_and_duplicate_are_reported_and_skipped(self) -> None:
        overlay, problems = self.read("class,crm_class,note\nQ100,dcat:Dataset,\nX1,crm:E73,\nQ999,crm:E73,\nQ100,crm:E73,\nQ100,crm:E73,\n", {"Q100"})
        self.assertEqual(overlay, {"Q100": ["crm:E73_Information_Object"]})
        self.assertEqual(len(problems), 4)
        self.assertTrue(any("allowed family" in p for p in problems))
        self.assertTrue(any("not an entity id" in p for p in problems))
        self.assertTrue(any("not an entity of this site" in p for p in problems))
        self.assertTrue(any("listed twice" in p for p in problems))

    def test_wrong_columns_are_one_problem(self) -> None:
        overlay, problems = self.read("a,b\n1,2\n")
        self.assertEqual((overlay, len(problems)), ({}, 1))

    def test_the_families_are_the_namespaces_the_n4o_profile_counts_as_crm(self) -> None:
        for prefix, namespace in crm.FAMILIES.items():
            self.assertTrue(namespace == "http://www.cidoc-crm.org/cidoc-crm/" or namespace.startswith("http://www.cidoc-crm.org/extensions/"), prefix)
        self.assertEqual(set(crm.FAMILIES), {"crm", "crmarchaeo", "crmdig", "crmgeo", "crmsci"})

    def test_the_alignment_of_an_extension_class_ends_at_the_first_crm_class(self) -> None:
        self.assertEqual(crm.chain("crmdig:D14"), [(D14, D1), (D1, E73)])
        self.assertEqual(crm.chain("crm:E73"), [])


class Inheriting(unittest.TestCase):
    def test_a_row_at_the_root_of_a_tree_anchors_everything_below_it(self) -> None:
        site = csv_site(OVERLAY)
        self.assertEqual([(a.curie, a.via) for a in site.crm_anchors("Q100")], [("crmdig:D14_Software", "Q100")])
        self.assertEqual([(a.curie, a.via) for a in site.crm_anchors("Q101")], [("crmdig:D14_Software", "Q100")])
        self.assertEqual([(a.curie, a.via) for a in site.crm_anchors("Q102")], [("crmdig:D14_Software", "Q100")])
        self.assertEqual(site.crm_anchors("Q103"), [])

    def test_a_row_of_its_own_comes_before_the_inherited_one(self) -> None:
        site = csv_site(OVERLAY + "Q101,crm:E73,\n")
        self.assertEqual([a.curie for a in site.crm_anchors("Q102")], ["crm:E73_Information_Object", "crmdig:D14_Software"])

    def test_the_classes_are_found_and_the_unanchored_one_is_named(self) -> None:
        site = csv_site(OVERLAY)
        self.assertEqual(site.crm_classes(), ["Q100", "Q101", "Q103"])
        self.assertEqual([c for c in site.crm_classes() if not site.crm_anchors(c)], ["Q103"])

    def test_without_the_kernel_and_without_class_properties_nothing_is_inherited(self) -> None:
        site = csv_site(OVERLAY)
        site.entities.pop("Q1")                       # no kernel ...
        site.entities.pop("P1")                       # ... and no property that says "subclass of" or "instance of"
        site.entities.pop("P2")
        self.assertFalse(site.has_kernel())
        self.assertEqual(site.class_properties(), (frozenset(), frozenset()))
        self.assertEqual(site.crm_edges(), {})
        self.assertEqual(site.crm_classes(), [])
        self.assertEqual([a.via for a in site.crm_anchors("Q100")], ["Q100"])
        self.assertEqual(site.crm_anchors("Q101"), [])


def wb_entity(entity_id: str, label: str, claims: dict | None = None, datatype: str | None = None) -> dict:
    """An entity in the JSON a Wikibase delivers (what ``harvest`` leaves in data/raw/entities)."""
    obj = {"id": entity_id, "type": "property" if entity_id[0] == "P" else "item", "labels": {"en": {"language": "en", "value": label}},
           "descriptions": {}, "aliases": {}, "claims": {}, "lastrevid": 1, "modified": "2026-01-01T00:00:00Z"}
    if datatype:
        obj["datatype"] = datatype
    for prop, targets in (claims or {}).items():
        obj["claims"][prop] = [{"id": f"{entity_id}${prop}-{n}", "type": "statement", "rank": "normal", "mainsnak": {
            "snaktype": "value", "property": prop, "datatype": "wikibase-item",
            "datavalue": {"type": "wikibase-entityid", "value": {"entity-type": "item", "id": target, "numeric-id": int(target[1:])}}}}
            for n, target in enumerate(targets)]
    return obj


def harvested_site(instance_of: str | None, subclass_of: str | None, overlay: str | None = OVERLAY) -> loader.Site:
    """A Wikibase that has no kernel: Q100 software > Q101 library, Q102 an item of Q101, Q103 a class of its own. The numbers of
    the two properties are the caller's (Wikibase Cloud has P1 and P2 either way round, Wikidata P31 and P279); ``None`` leaves
    the property out, as a copy of Wikidata does."""
    entities = [wb_entity("Q100", "software"), wb_entity("Q101", "library", {subclass_of or "P279": ["Q100"]}),
                wb_entity("Q102", "Numpy", {instance_of or "P31": ["Q101"]}), wb_entity("Q103", "loose class", {subclass_of or "P279": ["Q200"]}),
                wb_entity("Q200", "root")]
    if instance_of and subclass_of:
        entities += [wb_entity(instance_of, "instance of", datatype="wikibase-item"), wb_entity(subclass_of, "subclass of", datatype="wikibase-item")]
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "raw" / "entities").mkdir(parents=True)
        for obj in entities:
            (base / "raw" / "entities" / f"{obj['id']}.json").write_text(json.dumps(obj), encoding="utf-8")
        if overlay is not None:
            (base / "crm.csv").write_text(overlay, encoding="utf-8")
        return loader.load_site(base / "raw", base / "derived")


class AnyWikibase(unittest.TestCase):
    """The overlay works on a site that has no kernel: the two properties are found by what the site says (the datatype and the
    English label), whatever their numbers are."""

    def test_the_numbers_of_wikibase_cloud_either_way_round(self) -> None:
        for instance_of, subclass_of in (("P1", "P2"), ("P2", "P1"), ("P31", "P279")):
            with self.subTest(instance_of=instance_of, subclass_of=subclass_of):
                site = harvested_site(instance_of, subclass_of)
                self.assertFalse(site.has_kernel())
                self.assertEqual(site.class_properties(), (frozenset({instance_of}), frozenset({subclass_of})))
                self.assertEqual([(a.curie, a.via) for a in site.crm_anchors("Q102")], [("crmdig:D14_Software", "Q100")])
                self.assertEqual(site.crm_classes(), ["Q100", "Q101", "Q103", "Q200"])
                self.assertEqual([c for c in site.crm_classes() if not site.crm_anchors(c)], ["Q103", "Q200"])

    def test_a_copy_of_wikidata_without_its_properties_uses_p31_and_p279(self) -> None:
        site = harvested_site(None, None)
        self.assertEqual(site.class_properties(), (frozenset({"P31"}), frozenset({"P279"})))
        self.assertEqual([a.via for a in site.crm_anchors("Q102")], ["Q100"])

    def test_a_property_with_another_label_or_datatype_is_not_taken(self) -> None:
        site = harvested_site("P1", "P2")
        site.entities["P1"].labels["en"] = "part of"
        site._class_properties = None
        self.assertEqual(site.class_properties()[0], frozenset())

    def test_the_kernel_still_means_p2_and_p1(self) -> None:
        self.assertEqual(csv_site(OVERLAY).class_properties(), (frozenset({"P2"}), frozenset({"P1"})))

    def test_the_export_spells_out_the_class_tree_and_reads_back(self) -> None:
        site = harvested_site("P2", "P1")
        result = rdf.build(site, rdf.Namespaces(BASE))
        triples = {(s.value, p.value, o.value) for s, p, o in result.crm}
        self.assertIn((BASE + "/entity/Q100", RDFS + "subClassOf", D14), triples)
        self.assertIn((BASE + "/entity/Q101", RDFS + "subClassOf", BASE + "/entity/Q100"), triples)
        self.assertIn((BASE + "/entity/Q102", rdf.RDF + "type", BASE + "/entity/Q101"), triples)
        self.assertNotIn((BASE + "/entity/Q103", RDFS + "subClassOf", BASE + "/entity/Q200"), {t for t in triples if t[2] == "x"})
        self.assertIn((BASE + "/entity/Q103", RDFS + "subClassOf", BASE + "/entity/Q200"), triples)   # Q200 is an item of the site

    def test_an_edge_to_an_item_the_site_does_not_hold_is_not_written(self) -> None:
        site = harvested_site("P2", "P1")
        site.entities.pop("Q200")
        result = rdf.build(site, rdf.Namespaces(BASE))
        self.assertNotIn((BASE + "/entity/Q103", RDFS + "subClassOf", BASE + "/entity/Q200"), {(s.value, p.value, o.value) for s, p, o in result.crm})

    def test_the_n4o_anchor_test_reaches_the_cidoc_crm_from_an_item(self) -> None:
        import rdflib
        result = rdf.build(harvested_site("P2", "P1"), rdf.Namespaces(BASE))
        graph = rdflib.Graph()
        graph.parse(data=rdf.to_turtle(result.triples, rdf.Namespaces(BASE), "", [(rdf.BRIDGE_TITLE, result.bridge), (rdf.CRM_TITLE, result.crm)]), format="turtle")
        query = f"""SELECT ?c WHERE {{ <{BASE}/entity/Q102> <{RDFS}subClassOf>|a/<{RDFS}subClassOf>* ?c .
                    FILTER(STRSTARTS(STR(?c), "http://www.cidoc-crm.org/cidoc-crm/")) }}"""
        self.assertEqual({str(r[0]) for r in graph.query(query)}, {E73})


class Exporting(unittest.TestCase):
    def test_the_class_says_subclass_of_the_crm_class_and_the_extension_is_aligned(self) -> None:
        result = rdf.build(csv_site(OVERLAY), rdf.Namespaces(BASE))
        # the anchoring itself: the class and the chain; the DCAT classes and the spelled-out class tree are tested in test_check_crm.py
        triples = {(s.value, p.value, o.value) for s, p, o in result.crm
                   if s.value == BASE + "/entity/Q100" or s.value.startswith("http://www.cidoc-crm.org/")}
        self.assertEqual(triples, {(BASE + "/entity/Q100", RDFS + "subClassOf", D14), (D14, RDFS + "subClassOf", D1), (D1, RDFS + "subClassOf", E73)})
        self.assertTrue(result.crm <= result.triples)
        self.assertEqual(set(result.by_entity["Q100"]) & result.crm, {t for t in result.crm if t[0] == rdf.Iri(BASE + "/entity/Q100")})

    def test_the_turtle_has_a_section_of_its_own_and_reads_back_to_the_same_graph(self) -> None:
        import rdflib
        result = rdf.build(csv_site(OVERLAY), rdf.Namespaces(BASE))
        text = rdf.to_turtle(result.triples, rdf.Namespaces(BASE), "", [(rdf.BRIDGE_TITLE, result.bridge), (rdf.CRM_TITLE, result.crm)])
        self.assertIn("# CIDOC CRM anchoring", text)
        self.assertIn("@prefix crmdig: <http://www.cidoc-crm.org/extensions/crmdig/> .", text)
        self.assertLess(text.index("# RDFS bridge"), text.index("# CIDOC CRM anchoring"))
        graph = rdflib.Graph()
        graph.parse(data=text, format="turtle")
        self.assertEqual(len(graph), len(result.triples))

    def test_the_n4o_anchor_test_reaches_the_cidoc_crm_from_an_item(self) -> None:
        """What n4o-kg-profile does: follow rdfs:subClassOf transitively until a class of the CRM namespaces is reached."""
        import rdflib
        result = rdf.build(csv_site(OVERLAY), rdf.Namespaces(BASE))
        graph = rdflib.Graph()
        graph.parse(data=rdf.to_turtle(result.triples, rdf.Namespaces(BASE), "", [(rdf.BRIDGE_TITLE, result.bridge), (rdf.CRM_TITLE, result.crm)]), format="turtle")
        query = f"""SELECT ?c WHERE {{ <{BASE}/entity/Q102> <{BASE}/prop/direct/P2>/<{BASE}/prop/direct/P1>*/<{RDFS}subClassOf>* ?c .
                    FILTER(STRSTARTS(STR(?c), "http://www.cidoc-crm.org/cidoc-crm/")) }}"""
        self.assertEqual({str(r[0]) for r in graph.query(query)}, {E73})

    def test_without_an_overlay_the_export_is_the_same_as_before(self) -> None:
        result = rdf.build(csv_site(None), rdf.Namespaces(BASE))
        self.assertEqual(result.crm, set())
        text = rdf.to_turtle(result.triples, rdf.Namespaces(BASE), "", [(rdf.BRIDGE_TITLE, result.bridge), (rdf.CRM_TITLE, result.crm)])
        self.assertNotIn("CIDOC CRM", text)
        self.assertNotIn("crmdig", text)
        self.assertEqual(text, rdf.to_turtle(result.triples, rdf.Namespaces(BASE), "", (rdf.BRIDGE_TITLE, result.bridge)))


class Page(test_build.Site):
    """The page of an item shows its CIDOC CRM class, and says where it came from; a site without an overlay shows nothing."""

    def test_an_item_shows_its_class_and_an_item_without_one_says_so(self) -> None:
        (self.root / "data" / "crm.csv").write_text("class,crm_class,note\nQ1,crm:E73,x\n", encoding="utf-8")
        self.build()
        page = self.page("Q1.html")
        self.assertIn('<p class="crm">', page)
        self.assertIn("<code>crm:E73_Information_Object</code>", page)
        self.assertIn('title="http://www.cidoc-crm.org/cidoc-crm/E73_Information_Object"', page)
        self.assertIn("none yet", self.page("Q2.html"))
        self.assertNotIn('<p class="crm">', self.page("P1.html"))              # a property has no CRM class

    def test_a_site_without_an_overlay_has_no_such_line(self) -> None:
        self.build()
        self.assertNotIn('class="crm"', self.page("Q1.html"))


class Querying(unittest.TestCase):
    def test_the_feature_is_there_only_with_an_overlay(self) -> None:
        self.assertIn("crm", sparql.site_features(csv_site(OVERLAY)))
        self.assertNotIn("crm", sparql.site_features(csv_site(None)))

    def test_the_default_query_is_left_out_without_an_overlay_and_kept_with_one(self) -> None:
        for overlay, kept in ((None, False), (OVERLAY, True)):
            queries = sparql.load_queries(None)
            sparql.apply_requirements(queries, sparql.site_features(csv_site(overlay)))
            self.assertEqual("crm-classes" in [q.id for q in queries.queries], kept)

    def test_the_crm_query_returns_the_class_with_its_crm_class(self) -> None:
        site = csv_site(OVERLAY)
        ns = rdf.Namespaces(BASE)
        result = rdf.build(site, ns)
        ttl = rdf.to_turtle(result.triples, ns, "", [(rdf.BRIDGE_TITLE, result.bridge), (rdf.CRM_TITLE, result.crm)])
        queries = sparql.load_queries(None)
        sparql.apply_language(queries, "en")
        crm_query = [q for q in queries.queries if q.id == "crm-classes"]
        self.assertEqual(len(crm_query), 1)
        run = sparql.run_all(ttl, crm_query, ns.prefixes())[0]
        self.assertIsNone(run["error"])
        self.assertEqual(run["rows"], 1)


if __name__ == "__main__":
    unittest.main()
