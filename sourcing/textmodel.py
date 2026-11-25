"""原文切分与相似度计算。

只依赖标准库。切分保留原文子串（含异体字、省略、标点），相似度在归一化后的
字符层面计算，以便识别"换个说法"的范文改写，并通过对齐结果指出被替换的槽位。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_KEEP = re.compile(r"[0-9A-Za-z一-鿿]+")
_SENTENCE_END = "。！？!?；;"
_CLAUSE_SPLIT = "，,；;"


def normalize(text: str) -> str:
    """全半角统一并剔除标点空白，仅保留汉字、字母与数字。"""
    folded = unicodedata.normalize("NFKC", text)
    return "".join(_KEEP.findall(folded))


@dataclass(frozen=True)
class Segment:
    """文档中的一个句段。

    ``seg_id`` 形如 ``T2-1-2``（文档-句序-句内段序，均从 1 起）；
    ``start``/``end`` 为原文切片位置，``text`` 即原文精确子串。
    """

    doc_id: str
    seg_id: str
    sentence_no: int
    clause_no: int
    start: int
    end: int
    text: str

    @property
    def normalized(self) -> str:
        return normalize(self.text)


def _find_span(full: str, text: str, cursor: int) -> tuple[int, int]:
    idx = full.find(text, cursor)
    if idx < 0:  # 防御：切分结果一定是原文子串
        raise ValueError(f"无法在原文中定位句段：{text!r}")
    return idx, idx + len(text)


def split_document(doc_id: str, text: str) -> list[Segment]:
    """先按句末标点切句，再按逗号/分号切句段，全部保留原文。"""
    segments: list[Segment] = []
    cursor = 0
    sentence_no = 0
    while cursor < len(text):
        end = next(
            (i + 1 for i in range(cursor, len(text)) if text[i] in _SENTENCE_END),
            len(text),
        )
        sentence = text[cursor:end]
        sentence_no += 1
        clause_no = 0
        inner = 0
        while inner < len(sentence):
            cut = next(
                (j + 1 for j in range(inner, len(sentence))
                 if sentence[j] in _CLAUSE_SPLIT),
                len(sentence),
            )
            piece = sentence[inner:cut]
            inner = cut
            if not piece.strip():
                continue
            clause_no += 1
            start, stop = _find_span(text, piece, cursor)
            segments.append(
                Segment(
                    doc_id=doc_id,
                    seg_id=f"{doc_id}-{sentence_no}-{clause_no}",
                    sentence_no=sentence_no,
                    clause_no=clause_no,
                    start=start,
                    end=stop,
                    text=piece,
                )
            )
        cursor = end
    return segments


def load_documents(path: str | Path) -> dict[str, dict]:
    """读取交接 JSON，返回以 id 为键的文档字典，保持录入顺序。"""
    import json

    with Path(path).open(encoding="utf-8") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{path} 应为记录对象的数组")
    return {row["id"]: row for row in rows}


def _bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)}


@dataclass(frozen=True)
class Similarity:
    """两个句段的相似度与对齐结果。"""

    left: Segment
    right: Segment
    bigram_jaccard: float
    char_jaccard: float
    block_ratio: float
    sequence_ratio: float
    fixed_blocks: tuple[str, ...]
    """对齐中保留下来的连续文字（归一化后）。"""
    replaced_slots: tuple[str, ...]
    """对齐中被替换/插入的部分，成对给出 ``左=>右``。"""

    @property
    def score(self) -> float:
        """综合分，等权组合四项，阈值由调用方按业务解释设定。"""
        return (
            self.bigram_jaccard
            + self.char_jaccard
            + self.block_ratio
            + self.sequence_ratio
        ) / 4

    @property
    def is_exact_copy(self) -> bool:
        return self.left.normalized == self.right.normalized and bool(
            self.left.normalized
        )


def compare(left: Segment, right: Segment) -> Similarity:
    """计算两个句段的相似度并对齐出固定块与替换槽位。"""
    a, b = left.normalized, right.normalized
    ga, gb = _bigrams(a), _bigrams(b)
    bigram_jaccard = len(ga & gb) / len(ga | gb) if ga | gb else 0.0
    ca, cb = set(a), set(b)
    char_jaccard = len(ca & cb) / len(ca | gb) if ca | cb else 0.0

    from difflib import SequenceMatcher

    matcher = SequenceMatcher(None, a, b, autojunk=False)
    ops = matcher.get_opcodes()
    fixed: list[str] = []
    slots: list[str] = []
    matched = 0
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            fixed.append(a[i1:i2])
            matched += i2 - i1
        elif tag in {"replace", "insert", "delete"}:
            old = a[i1:i2] or "∅"
            new = b[j1:j2] or "∅"
            slots.append(f"{old}=>{new}")
    longest = max((blk.size for blk in matcher.get_matching_blocks()), default=0)
    denom = max(len(a), len(b), 1)
    return Similarity(
        left=left,
        right=right,
        bigram_jaccard=round(bigram_jaccard, 4),
        char_jaccard=round(char_jaccard, 4),
        block_ratio=round(longest / denom, 4),
        sequence_ratio=round(matcher.ratio(), 4),
        fixed_blocks=tuple(fixed),
        replaced_slots=tuple(slots),
    )
