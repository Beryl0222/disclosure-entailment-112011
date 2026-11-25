"""行动候选抽取与段落拆分认定测试。"""
import unittest

from sourcing.workspace import load_workspace

DATA = __import__("pathlib").Path(__file__).resolve().parents[1] / "data"


class ClaimTests(unittest.TestCase):
    def setUp(self):
        self.ws = load_workspace(DATA)
        self.by_id = {c.claim_id: c for c in self.ws.claims}

    def _site_claims(self, site):
        return [c for c in self.ws.claims if c.site == site]

    def test_template_commitment_is_separate_from_implemented_action(self):
        south = {c.practice: c for c in self._site_claims("南站")}
        # 范文承诺的巡检与自写的回用设施分成不同候选
        self.assertEqual(south["巡检"].role, "commitment")
        self.assertEqual(south["回用"].role, "implemented")

    def test_north_station_self_built_system_is_independent_candidate(self):
        north = {c.practice: c for c in self._site_claims("北站")}
        reuse = north["回用"]
        self.assertEqual(reuse.role, "implemented")
        # 采访核实了北站自有换热器，且否定了与南站同项目
        self.assertEqual(reuse.status, "interview_verified")
        self.assertTrue(
            any(ev.kind == "interview" for ev in reuse.evidence)
        )
        self.assertTrue(
            any(
                "text_only_reuse" in self._link_kind(lid)
                for lid in reuse.source_links
            )
        )

    def _link_kind(self, link_id):
        link = next(
            (x for x in self.ws.graph.links if x.link_id == link_id), None
        )
        return link.kind if link else ""

    def test_referenced_peer_project_is_not_native_action(self):
        west = self._site_claims("西站")
        peer = next(c for c in west if c.role == "referenced_peer")
        self.assertIn("青瓦", peer.project_name)
        # 明确未开展的回用单独成候选
        negated = next(c for c in west if c.role == "negated")
        self.assertEqual(negated.practice, "回用")

    def test_same_action_multiple_reports_merges_into_one_claim(self):
        tingwan_code = [
            c for c in self.ws.claims
            if c.site == "汀湾" and c.project_name.endswith("回用一号")
            and c.practice == "回用"
        ]
        self.assertEqual(len(tingwan_code), 1)
        claim = tingwan_code[0]
        # T5 与 T8 两篇发稿都挂在同一候选上作为出处
        sources = {ev.source_id for ev in claim.evidence}
        self.assertIn("T5", sources)
        self.assertIn("T8", sources)

    def test_steam_condensate_is_energy_recovery_not_general_reuse(self):
        energy = [
            c for c in self.ws.claims if c.practice == "能量回收"
        ]
        sites = {c.site for c in energy}
        self.assertIn("汀湾", sites)
        self.assertIn("长塘", sites)
        for claim in energy:
            self.assertNotEqual(claim.project_name, "汀湾-回用一号")

    def test_pending_relation_marks_claim_source_pending(self):
        pending = [
            c for c in self.ws.claims if c.status == "source_pending"
        ]
        self.assertTrue(pending)
        for claim in pending:
            self.assertTrue(claim.source_links)

    def test_every_claim_traces_back_to_segments_and_text(self):
        for claim in self.ws.claims:
            self.assertTrue(claim.segments)
            for seg_id in claim.segments:
                seg = self.ws.graph.segments[seg_id]
                self.assertEqual(seg.doc_id, seg_id.split("-", 1)[0])
                self.assertTrue(seg.text)

    def test_distinguish_claimed_vs_verified_status(self):
        statuses = {c.status for c in self.ws.claims}
        # 同一批材料中应同时存在文字所称、采访核实、现场核实三种状态
        self.assertIn("text_claimed", statuses)
        self.assertIn("interview_verified", statuses)
        self.assertIn("site_verified", statuses)


if __name__ == "__main__":
    unittest.main()
