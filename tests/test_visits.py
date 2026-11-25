"""访查选样、覆盖缺口与余量说明测试。"""
import unittest

from sourcing.visits import (
    GROUP_SITE_LIMIT,
    ROUND_LIMIT,
    build_plan,
    parse_windows,
)
from sourcing.workspace import load_workspace, parse_research_cells

DATA = __import__("pathlib").Path(__file__).resolve().parents[1] / "data"


class VisitPlanTests(unittest.TestCase):
    def setUp(self):
        self.ws = load_workspace(DATA)
        self.plan = self.ws.plan

    def test_confirmed_and_completed_visits_are_kept_first(self):
        self.assertEqual(self.plan.kept_visits, ["V1", "V2"])
        v1 = self.plan.find("V1")
        v2 = self.plan.find("V2")
        self.assertEqual(v1.decision, "keep")
        self.assertEqual(v2.decision, "keep")

    def test_completed_visit_keeps_actual_site_and_verified_scope(self):
        v1 = self.plan.find("V1")
        self.assertEqual(v1.site, "南站")
        # 只核实了青瓦回用；"未见巡检台账"不登记为已核实
        self.assertEqual(v1.verified_claim_ids, ["C001"])
        self.assertNotIn("C002", v1.verified_claim_ids)

    def test_same_site_supplement_merges_without_taking_slot(self):
        v5 = self.plan.find("V5")
        self.assertEqual(v5.decision, "merge")
        self.assertEqual(v5.merged_into, "V2")
        self.assertIn("V5", self.plan.merged_visits)
        # 合并窗口不产生新的实地访问
        self.assertNotIn("V5", self.plan.added_visits)

    def test_non_receptive_factory_is_blocked(self):
        v6 = self.plan.find("V6")
        self.assertEqual(v6.decision, "blocked")
        leftover = next(
            x for x in self.plan.leftovers if x.visit_id == "V6"
        )
        self.assertEqual(leftover.reason_code, "not_receptive")

    def test_round_and_group_limits_are_respected(self):
        decisions = [v for v in self.plan.visits if v.decision in {"keep", "add"}]
        self.assertLessEqual(len(decisions), ROUND_LIMIT)
        groups: dict[str, set[str]] = {}
        for v in decisions:
            actor = next(
                a for a in self.ws.actors.values() if a["场址"] == v.site
            )
            groups.setdefault(actor["集团"], set()).add(v.site)
        for sites in groups.values():
            self.assertLessEqual(len(sites), GROUP_SITE_LIMIT)

    def test_equal_coverage_prefers_earlier_window(self):
        # 长塘 V4(04-13) 与汀湾 V3(04-14) 同样补 2024 材料格子，
        # 研究规定同覆盖优先更早窗口，故新增 V4 而非 V3。
        self.assertEqual(self.plan.added_visits, ["V4"])
        self.assertNotIn("V3", self.plan.added_visits)
        # V3 排不进本轮，作为余量说明原因
        leftover = next(
            x for x in self.plan.leftovers if x.visit_id == "V3"
        )
        self.assertEqual(leftover.reason_code, "no_window")

    def test_leftovers_explain_why_not_scheduled(self):
        codes = {x.reason_code for x in self.plan.leftovers}
        # 三类余量都应可解释：无法接触 / 没有窗口 / （本轮）已有覆盖
        self.assertIn("not_receptive", codes)
        self.assertIn("no_window", codes)

    def test_coverage_board_distinguishes_covered_candidate_empty(self):
        states = {(c.industry, c.year, c.practice): c.state
                  for c in self.plan.cells}
        self.assertEqual(states[("装配", 2025, "回用")], "covered")
        self.assertEqual(states[("材料", 2025, "能量回收")], "candidate")
        self.assertEqual(states[("装配", 2024, "能量回收")], "empty")

    def test_window_bookability_uses_actor_and_window_flags(self):
        windows = parse_windows(self.ws.visit_rows, self.ws.actors)
        bookable = {w.visit_id: w.bookable for w in windows}
        self.assertFalse(bookable["V6"])  # 西站不可接待
        self.assertTrue(bookable["V4"])

    def test_research_cells_parse_all_dimensions(self):
        cells = parse_research_cells(self.ws.research_rows)
        self.assertEqual(len(cells), 12)  # 2 行业 × 2 年度 × 3 做法
        industries = {c[0] for c in cells}
        self.assertEqual(industries, {"装配", "材料"})


if __name__ == "__main__":
    unittest.main()
