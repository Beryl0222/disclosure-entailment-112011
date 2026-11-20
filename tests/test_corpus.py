"""交接资料格式和原文完整性测试。"""
from pathlib import Path
import json
import subprocess
import sys
import unittest

from corpus import read_collection

ROOT = Path(__file__).resolve().parents[1]


def records(name):
    return read_collection(ROOT / "data" / (name + ".json"))


class MaterialTests(unittest.TestCase):
    def test_collections_are_utf8_record_arrays(self):
        for name, fields in FIELDS.items():
            with self.subTest(collection=name):
                rows = records(name)
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(set(row), set(fields))
                    self.assertIsInstance(row["id"], str)
                    self.assertTrue(row["id"])

    def test_reader_retains_exact_text_and_order(self):
        result = subprocess.check_output(
            [sys.executable, "-m", "corpus", PRIMARY, "--id", LINE_ID],
            cwd=ROOT, text=True, encoding="utf-8",
        )
        original = [row for row in records(PRIMARY) if row["id"] == LINE_ID]
        self.assertTrue(original)
        self.assertEqual(json.loads(result), original)

    def test_disclosure_sources_and_visits_retain_independent_identity(self):
        actors = {row["id"]: row for row in records("actors")}
        documents = {row["id"]: row for row in records("texts")}
        for row in documents.values():
            self.assertIn(row["主体"], actors)
        places = {row["场址"] for row in actors.values()}
        for visit in records("visits"):
            self.assertIn(visit["场址"], places)
        self.assertEqual(actors["A"]["集团"], actors["B"]["集团"])
        self.assertNotEqual(actors["A"]["场址"], actors["B"]["场址"])
        self.assertLess(documents["T6"]["发布"], documents["T1"]["发布"])
        self.assertGreater(documents["T6"]["收到"], documents["T1"]["收到"])


PRIMARY = 'texts'
LINE_ID = 'T2'
FIELDS = {
    "texts": [
        "id",
        "主体",
        "年度",
        "类别",
        "发布",
        "收到",
        "文字"
    ],
    "actors": [
        "id",
        "名称",
        "场址",
        "行业",
        "集团",
        "可接待"
    ],
    "research": [
        "id",
        "原文"
    ],
    "visits": [
        "id",
        "日期",
        "场址",
        "人员",
        "状态",
        "目标"
    ]
}
