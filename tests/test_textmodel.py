"""句段切分与相似度测试。"""
import unittest

from sourcing.textmodel import (
    Segment,
    compare,
    normalize,
    split_document,
)


class TextModelTests(unittest.TestCase):
    def test_normalize_folds_fullwidth_and_drops_punctuation(self):
        self.assertEqual(normalize("园区，原则上。"), "园区原则上")
        # 全角字母数字折叠为半角，连字符作为标点被剔除
        self.assertEqual(normalize("Ｔ６－１"), "T61")

    def test_split_keeps_exact_substrings_and_positions(self):
        text = "本园区着力提高回用水比率，原则上每年进行用水巡检。可补填。"
        segments = split_document("T6", text)
        self.assertEqual(segments[0].seg_id, "T6-1-1")
        self.assertEqual(segments[1].seg_id, "T6-1-2")
        self.assertEqual(segments[2].seg_id, "T6-2-1")
        for seg in segments:
            self.assertEqual(text[seg.start:seg.end], seg.text)

    def test_exact_copy_is_detected(self):
        left = split_document("A", "本园区着力提高回用水比率，")[0]
        right = split_document("B", "本园区着力提高回用水比率，")[0]
        sim = compare(left, right)
        self.assertTrue(sim.is_exact_copy)
        # 精确复制：二元组 Jaccard 与序列比为 1，无替换槽位
        self.assertEqual(sim.bigram_jaccard, 1.0)
        self.assertEqual(sim.sequence_ratio, 1.0)
        self.assertEqual(sim.replaced_slots, ())

    def test_paraphrase_exposes_replaced_slots(self):
        left = split_document("A", "原则上每年进行用水巡检。")[0]
        right = split_document("B", "园区原则上逐年巡检。")[0]
        sim = compare(left, right)
        self.assertFalse(sim.is_exact_copy)
        # 固定块保留"原则/巡检"等骨架，槽位记录被替换部分
        joined = "".join(sim.fixed_blocks)
        self.assertIn("巡检", joined)
        self.assertTrue(sim.replaced_slots)
        self.assertGreater(sim.score, 0.2)

    def test_unrelated_industry_terms_score_low(self):
        left = split_document("A", "汀湾工厂已有可查的蒸汽回收装置，")[0]
        right = split_document("B", "长塘化工场已实施冷凝水回收。")[0]
        sim = compare(left, right)
        self.assertLess(sim.score, 0.25)


if __name__ == "__main__":
    unittest.main()
