"""新证据接入、再规划与导出材料测试。"""
import json
import tempfile
import unittest
from pathlib import Path

from sourcing.textmodel import load_documents
from sourcing.workspace import export_grouping, load_workspace, revise

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FIXTURES = ROOT / "tests" / "fixtures"


class ReviseTests(unittest.TestCase):
    def test_earlier_template_changes_attribution_but_keeps_visits(self):
        ws = load_workspace(DATA)
        before_visit = ws.plan.find("V1")
        earlier = list(
            load_documents(FIXTURES / "earlier_template.json").values()
        )
        revise(ws, new_documents=earlier)
        # 新范文产生确认的复用关系
        kinds = [
            (link.kind, link.status)
            for link in ws.graph.links
            if any("NT1" in ev for ev in link.evidence)
        ]
        self.assertTrue(kinds)
        self.assertIn(("template_reuse", "confirmed"), kinds)
        # 已完成访查的日期、场址、决定不变
        after = ws.plan.find("V1")
        self.assertEqual(after.site, before_visit.site)
        self.assertEqual(after.date, before_visit.date)
        self.assertEqual(after.decision, "keep")
        self.assertTrue(
            any("更早范文" in entry for entry in ws.change_log)
        )

    def test_new_interview_distinguishes_two_projects(self):
        ws = load_workspace(DATA)
        interview = list(
            load_documents(FIXTURES / "new_interview.json").values()
        )
        revise(ws, interview_documents=interview)
        # 汀湾/长塘的"回用一号"同项目假设被采访否定
        refuted = [
            link
            for link in ws.graph.links
            if "NI1" in link.evidence and link.status == "refuted"
        ]
        self.assertTrue(refuted)
        # 两个场址的候选仍然各自保留，没有被并成一家
        sites = {
            c.site
            for c in ws.claims
            if "回用一号" in c.project_name
        }
        self.assertEqual(sites, {"汀湾", "长塘"})
        self.assertTrue(
            any("采访" in entry for entry in ws.change_log)
        )

    def test_revise_rejects_duplicate_document_id(self):
        ws = load_workspace(DATA)
        dup = [dict(ws.documents["T1"])]
        with self.assertRaises(ValueError):
            revise(ws, new_documents=dup)

    def test_completed_visit_survives_any_revision(self):
        ws = load_workspace(DATA)
        interview = list(
            load_documents(FIXTURES / "new_interview.json").values()
        )
        revise(ws, interview_documents=interview)
        v1 = ws.plan.find("V1")
        self.assertEqual(v1.decision, "keep")
        self.assertEqual(v1.verified_claim_ids, ["C001"])

    def test_export_grouping_is_traceable(self):
        ws = load_workspace(DATA)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "grouping.json"
            export_grouping(ws, out)
            payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("claims", payload)
        self.assertIn("visits", payload)
        self.assertIn("coverage", payload)
        # 每个候选都能回到原段与来源关系
        for claim in payload["claims"]:
            self.assertTrue(claim["segments"])
            self.assertTrue(claim["status"])
        # 访查对象可回溯到候选 id
        visit_ids = {v["visit_id"] for v in payload["visits"]}
        self.assertIn("V1", visit_ids)
        # 明确区分文字所称与采访/现场核实
        statuses = {c["status"] for c in payload["claims"]}
        self.assertTrue(
            {"text_claimed", "interview_verified", "site_verified"}
            & statuses
        )


if __name__ == "__main__":
    unittest.main()
