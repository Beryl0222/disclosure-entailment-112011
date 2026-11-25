"""可持续披露文本：来源复用分析、行动候选与访查选样。

模块划分：

- ``textmodel``：原文切句切段、归一化与相似度/替换槽位计算
- ``provenance``：段间关系（范文复用、引用、同一项目、仅术语共享）与同源传递
- ``claims``：从段落中抽取本场址行动候选，区分自写部分与模板承诺
- ``visits``：访查约束解析、窗口选样、覆盖缺口与余量说明
- ``workspace``：把采访与新范文作为新证据接入后的再规划
"""

from .textmodel import Segment, Similarity, load_documents, split_document
from .provenance import Link, ProvenanceGraph, build_graph
from .claims import Claim, extract_claims
from .visits import Plan, build_plan
from .workspace import Workspace, revise

__all__ = [
    "Segment",
    "Similarity",
    "load_documents",
    "split_document",
    "Link",
    "ProvenanceGraph",
    "build_graph",
    "Claim",
    "extract_claims",
    "Plan",
    "build_plan",
    "Workspace",
    "revise",
]
