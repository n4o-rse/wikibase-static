"""Tests for the data-model graphics (S16) and for the prefix family of the RDF export.

    python tests/test_modelgraph.py

The pictures are SVG text, so the tests read them as XML and look for what a reader would: the links, the shared reference,
the escaped labels, the class cards and their counts.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))

import rdflib  # noqa: E402

from wikibase_static import rdf  # noqa: E402
from wikibase_static.loader import Site  # noqa: E402
from wikibase_static.model import Entity, Snak, Statement  # noqa: E402
from wikibase_static.modelgraph import ModelGraphs, fit, text_width  # noqa: E402
from wikibase_static.render import STRINGS, Renderer  # noqa: E402
from wikibase_static.site_config import SiteConfig, load_config  # noqa: E402

SVG = "{http://www.w3.org/2000/svg}"
BASE = "https://wb.example.org"


def item_ref(prop: str, target: str) -> Snak:
    return Snak(property=prop, snaktype="value", datatype="wikibase-item", vtype="wikibase-entityid",
                value={"entity-type": "item", "id": target})


def text_snak(prop: str, text: str) -> Snak:
    return Snak(property=prop, snaktype="value", datatype="string", vtype="string", value=text)


def statement(main: Snak, qualifiers=None, references=None, rank: str = "normal") -> Statement:
    return Statement(id=None, mainsnak=main, rank=rank, qualifiers=qualifiers or [], references=references or [])


def make_site() -> Site:
    """Two classes (Q1 tool, Q2 plugin, a subclass), two instances of Q1, one of Q2; P1 instance of, P2 subclass of, P3 name, P4 made by."""
    site = Site()

    def add(entity: Entity) -> Entity:
        site.entities[entity.id] = entity
        return entity

    add(Entity("P1", "property", "wikibase-item", labels={"en": "instance of"}))
    add(Entity("P2", "property", "wikibase-item", labels={"en": "subclass of"}))
    add(Entity("P3", "property", "string", labels={"en": "name"}))
    add(Entity("P4", "property", "wikibase-item", labels={"en": "made by"}))
    add(Entity("P5", "property", "string", labels={"en": "source"}))
    add(Entity("Q1", "item", labels={"en": "tool"}))
    add(Entity("Q2", "item", labels={"en": "plugin"}, statements=[statement(item_ref("P2", "Q1"))]))
    add(Entity("Q3", "item", labels={"en": "Ada <&> Co"}))
    reference = [[text_snak("P5", "https://example.org/source")]]
    add(Entity("Q10", "item", labels={"en": "Hammer"}, statements=[
        statement(item_ref("P1", "Q1")),
        statement(text_snak("P3", "Hammer"), references=reference),
        statement(item_ref("P4", "Q3"), qualifiers=[text_snak("P3", "since 2020")], references=reference, rank="preferred"),
    ]))
    add(Entity("Q11", "item", labels={"en": "Saw"}, statements=[statement(item_ref("P1", "Q1")), statement(text_snak("P3", "Saw"))]))
    add(Entity("Q12", "item", labels={"en": "Drill plugin"}, statements=[statement(item_ref("P1", "Q2")), statement(item_ref("P4", "Q3"))]))
    return site


def graphs_of(site: Site) -> ModelGraphs:
    return ModelGraphs(Renderer(site, SiteConfig(), "test"))


class EntityGraph(unittest.TestCase):
    def setUp(self) -> None:
        self.site = make_site()
        self.graphs = graphs_of(self.site)

    def test_it_is_well_formed_svg_with_a_title(self) -> None:
        root = ET.fromstring(self.graphs.entity_svg(self.site.entities["Q10"]))
        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("Statement graph", "".join(root.itertext()))

    def test_an_entity_without_statements_has_no_graph(self) -> None:
        self.assertIsNone(self.graphs.entity_svg(self.site.entities["Q1"]))

    def test_item_values_link_to_their_pages_and_the_base_is_prefixed(self) -> None:
        svg = self.graphs.entity_svg(self.site.entities["Q10"])
        self.assertIn('href="Q3.html"', svg)
        self.assertIn('href="Q1.html"', self.graphs.entity_svg(self.site.entities["Q10"]))
        self.assertIn('href="../Q3.html"', self.graphs.entity_svg(self.site.entities["Q10"], base="../"))

    def test_labels_are_escaped(self) -> None:
        svg = self.graphs.entity_svg(self.site.entities["Q10"])
        self.assertIn("Ada &lt;&amp;&gt; Co", svg)
        self.assertNotIn("Ada <&> Co", svg)
        ET.fromstring(svg)

    def test_a_reference_two_statements_share_is_drawn_once_with_its_count(self) -> None:
        svg = self.graphs.entity_svg(self.site.entities["Q10"])
        self.assertIn("Reference shared by 2 of 3 statements", svg)
        self.assertEqual(svg.count("https://example.org/source"), 1)

    def test_an_own_reference_is_a_dashed_chip_under_its_value(self) -> None:
        site = make_site()
        site.entities["Q11"].statements[1].references.append([text_snak("P5", "https://example.org/own")])
        svg = graphs_of(site).entity_svg(site.entities["Q11"])
        self.assertIn("mg-meta mg-ref", svg)
        self.assertIn("https://example.org/own", svg)
        self.assertNotIn("Reference shared", svg)

    def test_a_qualifier_is_a_chip_and_a_preferred_rank_a_thick_outline(self) -> None:
        svg = self.graphs.entity_svg(self.site.entities["Q10"])
        self.assertIn("name: since 2020", svg)
        self.assertIn("mg-pref", svg)

    def test_a_class_is_orange_and_a_plain_item_grey(self) -> None:
        svg = self.graphs.entity_svg(self.site.entities["Q10"])
        self.assertIn("mg-class", svg)       # Q1, the class
        self.assertIn("mg-item", svg)        # Q3, an item
        self.assertIn("mg-self", svg)        # Q10, the entity itself

    def test_the_picture_is_the_same_every_time(self) -> None:
        first = self.graphs.entity_svg(self.site.entities["Q10"])
        self.assertEqual(first, graphs_of(make_site()).entity_svg(make_site().entities["Q10"]))
        self.assertEqual(first, self.graphs.entity_svg(self.site.entities["Q10"]))

    def test_many_values_wrap_into_lines_inside_the_picture(self) -> None:
        site = make_site()
        for number in range(40):
            site.entities[f"Q{100 + number}"] = Entity(f"Q{100 + number}", "item", labels={"en": f"Value {number}"})
        site.entities["Q10"].statements = [statement(item_ref("P4", f"Q{100 + n}")) for n in range(40)]
        svg = graphs_of(site).entity_svg(site.entities["Q10"])
        root = ET.fromstring(svg)
        width = float(root.get("viewBox").split()[2])
        for rect in root.iter(SVG + "rect"):
            self.assertLessEqual(float(rect.get("x")) + float(rect.get("width")), width, rect.attrib)

    def test_long_text_is_cut_with_an_ellipsis_and_kept_in_the_tooltip(self) -> None:
        site = make_site()
        long_text = "x" * 400
        site.entities["Q11"].statements = [statement(text_snak("P3", long_text))]
        svg = graphs_of(site).entity_svg(site.entities["Q11"])
        self.assertIn("…", svg)
        self.assertIn(f"<title>{long_text}</title>", svg)

    def test_every_text_key_exists_in_both_languages(self) -> None:
        keys = {key for key in STRINGS["en"] if key.startswith(("graph_", "model_"))}
        self.assertTrue(keys)
        self.assertEqual(keys, {key for key in STRINGS["de"] if key.startswith(("graph_", "model_"))})


class SiteGraph(unittest.TestCase):
    def test_one_card_per_class_with_its_count_and_property_rows(self) -> None:
        site = make_site()
        svg = graphs_of(site).site_svg()
        ET.fromstring(svg)
        text = "".join(ET.fromstring(svg).itertext())
        self.assertIn("tool", text)
        self.assertIn("2 instance(s)", text)         # Q10, Q11
        self.assertIn("plugin", text)
        self.assertIn("made by", text)
        self.assertIn("name", text)

    def test_the_typing_properties_are_not_rows(self) -> None:
        text = "".join(ET.fromstring(graphs_of(make_site()).site_svg()).itertext())
        self.assertNotIn("instance of", text)
        self.assertNotIn("subclass of", text)

    def test_values_are_named_by_class_when_the_target_has_one(self) -> None:
        site = make_site()
        site.entities["Q3"].statements = [statement(item_ref("P1", "Q2"))]      # Ada is a plugin now
        text = "".join(ET.fromstring(graphs_of(site).site_svg()).itertext())
        self.assertIn("plugin", text)

    def test_classes_with_the_same_instances_share_one_card(self) -> None:
        site = make_site()
        site.entities["Q4"] = Entity("Q4", "item", labels={"en": "gadget"})
        for instance in ("Q10", "Q11"):                                  # the same two items are tools and gadgets
            site.entities[instance].statements.append(statement(item_ref("P1", "Q4")))
        svg = graphs_of(site).site_svg()
        root = ET.fromstring(svg)
        text = "".join(root.itertext())
        self.assertIn("tool · gadget", text)
        self.assertEqual(text.count("2 instance(s)"), 1)                 # one card, not two
        self.assertEqual(sum(1 for r in root.iter("rect") if r.get("class") == "mg-card"), 2)   # tool·gadget and plugin
        titles = [t.text for t in root.iter("title")]
        self.assertIn("tool (Q1), gadget (Q4)", titles)

    def test_classes_with_different_instances_keep_their_own_cards(self) -> None:
        site = make_site()
        site.entities["Q4"] = Entity("Q4", "item", labels={"en": "gadget"})
        site.entities["Q10"].statements.append(statement(item_ref("P1", "Q4")))      # only one of the two tools
        text = "".join(ET.fromstring(graphs_of(site).site_svg()).itertext())
        self.assertNotIn("·", text)
        self.assertIn("gadget", text)

    def test_a_site_without_classes_has_no_model_graph(self) -> None:
        site = Site()
        site.entities["Q1"] = Entity("Q1", "item", labels={"en": "lonely"})
        self.assertIsNone(graphs_of(site).site_svg())

    def test_the_standalone_file_has_a_namespace_and_prefixed_links(self) -> None:
        svg = graphs_of(make_site()).site_svg("../", standalone=True)
        self.assertTrue(svg.startswith('<?xml version="1.0"'))
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', svg)
        self.assertIn('href="../Q1.html"', svg)
        ET.fromstring(svg.encode("utf-8"))


class TextHelpers(unittest.TestCase):
    def test_fit_keeps_short_text_and_cuts_long_text(self) -> None:
        self.assertEqual(fit("short", 200), "short")
        cut = fit("a very long label that cannot fit", 80)
        self.assertTrue(cut.endswith("…"))
        self.assertLessEqual(text_width(cut), 80 + 13)

    def test_wide_characters_count_full(self) -> None:
        self.assertGreater(text_width("漢字"), text_width("ab"))


class PrefixFamily(unittest.TestCase):
    def test_without_a_family_the_wikidata_names_are_used(self) -> None:
        names = rdf.Namespaces(BASE).prefixes()
        for name in ("wd", "wdt", "wds", "p", "ps", "pq", "pr", "wdref", "wdv", "data", "cat", "dist"):
            self.assertIn(name, names)
        self.assertEqual(names["data"], BASE + "/wiki/Special:EntityData/")
        self.assertEqual(rdf.Namespaces(BASE).dataset("Q1"), BASE + "/wiki/Special:EntityData/Q1")

    def test_a_family_renames_every_wikibase_prefix_and_none_collides(self) -> None:
        ns = rdf.Namespaces(BASE, "chb")
        names = ns.prefixes()
        for name in ("wd", "wdt", "wds", "wdref", "wdv", "wdno", "data", "cat", "dist"):
            self.assertNotIn(name, names)
        self.assertEqual(names["chb"], BASE + "/entity/")
        self.assertEqual(names["chbs"], BASE + "/entity/statement/")
        self.assertEqual(names["chbt"], BASE + "/prop/direct/")
        self.assertEqual(names["chbp"], BASE + "/prop/")
        self.assertEqual(names["chbps"], BASE + "/prop/statement/")
        self.assertEqual(names["chbpsv"], BASE + "/prop/statement/value/")
        self.assertEqual(names["chbpq"], BASE + "/prop/qualifier/")
        self.assertEqual(names["chbpr"], BASE + "/prop/reference/")
        self.assertEqual(names["chbref"], BASE + "/reference/")
        self.assertEqual(names["chbv"], BASE + "/value/")
        self.assertEqual(len(set(names.values())), len(names))        # no two prefixes for one namespace

    def test_the_namespaces_do_not_depend_on_the_family(self) -> None:
        plain, family = rdf.Namespaces(BASE), rdf.Namespaces(BASE, "chb")
        for attribute in ("wd", "wds", "wdt", "p", "ps", "psv", "pq", "pqv", "pr", "prv", "wdno", "wdref", "wdv", "cat", "dist"):
            self.assertEqual(getattr(plain, attribute), getattr(family, attribute), attribute)

    def test_a_family_points_the_dataset_at_the_file_that_exists(self) -> None:
        ns = rdf.Namespaces(BASE, "chb")
        self.assertEqual(ns.dataset("Q933"), BASE + "/ttl/Q933.ttl")

    def test_the_turtle_is_the_same_graph_under_either_naming(self) -> None:
        site = make_site()
        graphs = []
        for family in (None, "chb"):
            ns = rdf.Namespaces(BASE, family)
            result = rdf.build(site, ns, "https://creativecommons.org/publicdomain/zero/1.0/", None)
            text = rdf.to_turtle(result.triples, ns, "")
            graph = rdflib.Graph()
            graph.parse(data=text, format="turtle")
            expected = rdflib.Graph()
            expected.parse(data=rdf.ntriples(result.triples), format="nt")
            self.assertTrue(graph.isomorphic(expected), family)
            graphs.append(text)
        self.assertIn("chbt:P3", graphs[1])
        self.assertIn("chbs:Q10-", graphs[1])
        self.assertNotIn("wdt:", graphs[1])
        self.assertIn("wdt:P3", graphs[0])

    def test_a_dotted_local_name_is_abbreviated_and_reads_back(self) -> None:
        from wikibase_static.step_rdf import write_published  # noqa: F401 - the module imports cleanly
        ns = rdf.Namespaces(BASE, "chb")
        catalog = rdf.CatalogInfo(title="t", description="d", license_url=None, source_url=None, pages_url=BASE + "/", modified=None,
                                  json_sizes={}, export_file="downloads/x.ttl", ontology_file="downloads/o.ttl", ontology_bytes=1)
        result = rdf.build(make_site(), ns, None, catalog)
        text = rdf.to_turtle(result.triples, ns, "")
        self.assertIn("chbdata:Q10.ttl", text)
        graph = rdflib.Graph()
        graph.parse(data=text, format="turtle")
        self.assertIn(rdflib.URIRef(BASE + "/ttl/Q10.ttl"), set(graph.subjects()))


class ConfigKey(unittest.TestCase):
    def load(self, text: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "site.yaml"
            path.write_text(text, encoding="utf-8")
            return load_config(path, None)

    def test_a_short_lower_case_name_is_taken(self) -> None:
        cfg = self.load("title: t\nrdf_prefix: chb\n")
        self.assertEqual(cfg.rdf_prefix, "chb")
        self.assertFalse([p for p in cfg.problems if "rdf_prefix" in p])

    def test_the_default_is_no_family(self) -> None:
        self.assertIsNone(self.load("title: t\n").rdf_prefix)

    def test_a_bad_or_reserved_name_is_reported_and_ignored(self) -> None:
        for bad in ("Chb", "1chb", "a-b", "rdf", "wikibase", "toolongprefixname"):
            cfg = self.load(f"title: t\nrdf_prefix: {bad}\n")
            self.assertIsNone(cfg.rdf_prefix, bad)
            self.assertTrue([p for p in cfg.problems if "rdf_prefix" in p], bad)


if __name__ == "__main__":
    unittest.main()
