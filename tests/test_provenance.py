"""来源关系、同源传递与采访证据测试。"""
import unittest

from sourcing.provenance import (
    TRANSITIVE_KINDS,
    build_graph,
)
from sourcing.textmodel import load_documents
from sourcing.workspace import load_workspace

DATA = __import__("pathlib").Path(__file__).resolve().parents[1] / "data"


def _load():
    documents = load_documents(DATA / "texts.json")
    actors = load_documents(DATA / "actors.json")
    return documents, actors, build_graph(documents, actors)


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.documents, self.actors, self.graph = _load()

    def _link(self, left, right):
        return next(
            link
            for link in self.graph.links
            if link.endpoints() == frozenset((left, right))
        )

    def test_exact_template_copy_is_confirmed_reuse(self):
        link = self._link("T6-1-1", "T1-1-1")
        self.assertEqual(link.kind, "template_reuse")
        self.assertEqual(link.status, "confirmed")
        self.assertIn("T6", link.evidence)

    def test_paraphrased_template_is_proposed_with_slots(self):
        link = self._link("T6-1-2", "T2-1-2")
        self.assertEqual(link.kind, "template_reuse")
        self.assertEqual(link.status, "proposed")
        self.assertTrue(link.similarity.replaced_slots)

    def test_same_site_project_descriptions_become_one_project(self):
        # T1 与集团 T3 都描述南站青瓦供冷项目
        link = self._link("T1-2-1", "T3-1-2")
        self.assertEqual(link.kind, "same_project")
        self.assertEqual(link.status, "confirmed")

    def test_tingwan_repeated_filing_is_same_project(self):
        link = self._link("T5-1-3", "T8-1-1")
        self.assertEqual(link.kind, "same_project")
        self.assertEqual(link.status, "confirmed")

    def test_shared_project_code_across_sites_stays_unconfirmed(self):
        # 汀湾与长塘都用"回用一号"，但不能仅凭术语证实同源
        for pair in (("T5-1-3", "T9-1-1"), ("T8-1-1", "T9-1-1")):
            link = self._link(*pair)
            self.assertEqual(link.kind, "shared_terms")
            self.assertEqual(link.status, "proposed")

    def test_interview_refutes_cross_site_project_and_records_text_copy(self):
        refuted = self._link("T1-2-1", "T2-2-1")
        self.assertEqual(refuted.kind, "shared_terms")
        self.assertEqual(refuted.status, "refuted")
        text_only = self._link("T2-2-1", "T3-1-2")
        self.assertEqual(text_only.kind, "shared_terms")
        self.assertEqual(text_only.status, "refuted")
        copied = next(
            link
            for link in self.graph.links
            if link.kind == "text_only_reuse"
            and link.endpoints() == frozenset(("T1-2-1", "T2-2-1"))
        )
        self.assertEqual(copied.status, "confirmed")
        self.assertIn("T7", copied.evidence)

    def test_alternatives_show_two_interpretations(self):
        alts = self.graph.alternatives("T9-1-1")
        self.assertTrue(alts)
        kinds = {item["kind"] for item in alts}
        self.assertIn("shared_terms", kinds)
        for item in alts:
            self.assertIn("if_shared_source", item)
            self.assertIn("if_independent", item)

    def test_transitivity_does_not_cross_project_via_generic_text(self):
        # 南站与北站被采访证明非同项目：same_project 无传递路径
        path = self.graph.explain_path(
            "T1-2-1", "T2-2-1", "same_project"
        )
        self.assertEqual(path, [])
        # 仅文字复用与共享术语不参与传递
        self.assertNotIn("text_only_reuse", TRANSITIVE_KINDS)
        self.assertNotIn("shared_terms", TRANSITIVE_KINDS)

    def test_template_reuse_transitivity_uses_confirmed_edges_only(self):
        family = self.graph.wording_family("T1-1-1")
        self.assertIn("T6-1-1", family)
        # 改写未确认的 T2 段不应进入已确认复用闭包
        self.assertNotIn("T2-1-2", family)

    def test_confirm_and_refute_by_researcher(self):
        link = self._link("T6-1-2", "T2-1-2")
        updated = self.graph.confirm(
            link.link_id, "研究员补录底文确认改写关系", "T6"
        )
        self.assertEqual(updated.status, "confirmed")
        family = self.graph.wording_family("T2-1-2")
        self.assertIn("T6-1-2", family)

    def test_workspace_loads_and_exposes_graph(self):
        ws = load_workspace(DATA)
        self.assertTrue(ws.graph.links)
        self.assertTrue(ws.claims)


if __name__ == "__main__":
    unittest.main()
