"""从句段中抽取本场址行动候选。

同一段文字可拆开认定：模板/引用部分只算出处，自写且落在本场址的措施才成为
访查候选。候选保留回到原段的引用，以及范文/采访来源链。

状态区分：

- ``text_claimed``       披露文字所称已经开展，尚未经采访核实
- ``interview_verified`` 采访纪要明确核实过的动作（R3 才可进入已核实资料）
- ``site_verified``      已完成现场访查在该场址核实到的动作
- ``source_pending``     存在未证实同源关系，合并与否影响候选身份
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .provenance import ProvenanceGraph
from .textmodel import Segment, split_document

# 做法类型关键词：能量回收/巡检先于泛化的"回用/回收"判断。
# 换热器在本语境内是废水回供冷设备的一部分，归入回用；
# "回用一号"是项目专名，无论句中出现什么动词都按回用项目处理。
PRACTICE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("能量回收", ("蒸汽", "冷凝", "能量")),
    ("巡检", ("巡检", "台账", "盘点")),
    ("回用", (
        "回用", "循环用水", "废水", "回收装置", "回收", "计量表",
        "用水计量", "换热", "供冷",
    )),
)
PROJECT_PRACTICE = {"青瓦": "回用", "回用一号": "回用"}
NEGATION_MARKERS = ("未建成", "还未", "尚未", "没有", "未启动", "未")
INTENT_MARKERS = ("拟", "计划", "原则上", "逐年", "每年")
DONE_MARKERS = (
    "已有", "已实施", "已完成", "已", "运行", "试转", "试运", "开始",
    "用于", "回到", "指",
)
COMMITMENT_MARKERS = ("原则上", "每年", "逐年")
REFERENCE_MARKERS = ("借鉴", "参照", "参考", "引用", "推给", "推广")
PLACE_PATTERN = re.compile(r"南站|北站|西站|汀湾|长塘")
PROJECT_PATTERN = re.compile(r"青瓦|回用一号")


@dataclass(frozen=True)
class Evidence:
    """一条候选的出处或核实证据。"""

    source_id: str
    seg_id: str | None
    quote: str
    kind: str
    """disclosure / template / interview / visit。"""


@dataclass
class Claim:
    """一个场址-做法-项目上的行动候选（同一实际行动只保留一个候选）。"""

    claim_id: str
    site: str
    actor_id: str
    practice: str
    years: set[int]
    role: str
    """implemented 已实施 / commitment 模板承诺 / intent 仅意向 /
    referenced_peer 引用同行 / negated 明确未开展。"""
    status: str
    project_name: str
    segments: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    source_links: list[str] = field(default_factory=list)
    """解释该候选文字来源或项目关系的 Link id。"""
    note: str = ""

    def key(self) -> tuple[str, str, str]:
        return (self.site, self.practice, self.project_name)


def classify_practice(text: str) -> str | None:
    # 项目专名优先：专名项目的做法身份不随句中动词改变
    for name, practice in PROJECT_PRACTICE.items():
        if name in text:
            return practice
    for practice, keywords in PRACTICE_RULES:
        if any(word in text for word in keywords):
            return practice
    return None


def _role_of(text: str) -> str:
    if any(marker in text for marker in NEGATION_MARKERS):
        return "negated"
    # "参照园区要求"是对模板要求的承诺，不是引用同行做法
    if any(marker in text for marker in REFERENCE_MARKERS) and not (
        "参照" in text and "园区" in text
    ):
        return "referenced_peer"
    if any(marker in text for marker in COMMITMENT_MARKERS) or (
        "参照" in text and "园区" in text
    ):
        return "commitment"
    if any(marker in text for marker in DONE_MARKERS):
        return "implemented"
    if any(marker in text for marker in INTENT_MARKERS) or "将" in text:
        return "intent"
    return "intent"


def _year_hint(text: str, doc_year: int) -> int:
    """文字中出现"去年"等相对年份时回溯，否则取文档报告年度。"""
    if "去年" in text:
        return doc_year - 1
    return doc_year


def _project_name(site: str, practice: str, text: str) -> str:
    found = PROJECT_PATTERN.search(text)
    if found:
        return f"{site}-{found.group(0)}"
    # 自写措施按设施名独立命名，避免与模板承诺并成同一候选
    facility = re.search(
        r"计量表|换热器|回收装置|冷凝水回收|蒸汽回收|蒸汽", text
    )
    if facility:
        return f"{site}-{facility.group(0)}"
    return f"{site}-{practice}"


def _related_links(graph: ProvenanceGraph, seg_id: str) -> list[str]:
    return sorted(
        link.link_id
        for link in graph.links_for(seg_id)
        if link.kind
        in {"template_reuse", "citation", "text_only_reuse", "shared_terms",
            "same_project"}
    )


def _has_pending_relation(graph: ProvenanceGraph, seg_id: str) -> bool:
    return any(
        link.status == "proposed"
        and link.kind in {"shared_terms", "same_project", "citation"}
        for link in graph.links_for(seg_id)
    )


def extract_claims(
    documents: dict[str, dict],
    actors: dict[str, dict],
    graph: ProvenanceGraph,
) -> list[Claim]:
    """抽取全部行动候选；同一实际行动的多篇发稿合并为一个候选。"""
    claims: dict[tuple[str, str, str], Claim] = {}
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"C{counter:03d}"

    for doc_id in sorted(documents):
        doc = documents[doc_id]
        if doc["类别"] in {"范文", "采访"}:
            continue  # 范文是来源而非本场实践；采访在核实阶段并入
        actor = actors.get(doc["主体"])
        if actor is None or not actor["场址"]:
            continue  # 集团/园区发稿没有场址，其项目描述随具体场址披露归并
        site = actor["场址"]
        for seg in split_document(doc_id, doc["文字"]):
            practice = classify_practice(seg.text)
            if practice is None:
                continue
            role = _role_of(seg.text)
            year = _year_hint(seg.text, int(doc["年度"]))
            project = _project_name(site, practice, seg.text)
            links = _related_links(graph, seg.seg_id)
            ev = Evidence(
                source_id=doc_id,
                seg_id=seg.seg_id,
                quote=seg.text,
                kind="disclosure",
            )
            key = (site, practice, project)
            if key in claims:
                claim = claims[key]
                claim.years.add(year)
                claim.segments.append(seg.seg_id)
                claim.evidence.append(ev)
                claim.source_links = sorted(set(claim.source_links) | set(links))
                _promote_role(claim, role)
                if claim.status == "source_pending" and not _has_pending_relation(
                    graph, seg.seg_id
                ):
                    pass
            else:
                status = (
                    "source_pending"
                    if _has_pending_relation(graph, seg.seg_id)
                    else "text_claimed"
                )
                note = (
                    "存在未证实同源关系，两种解释见来源图 alternatives"
                    if status == "source_pending"
                    else ""
                )
                claims[key] = Claim(
                    claim_id=next_id(),
                    site=site,
                    actor_id=doc["主体"],
                    practice=practice,
                    years={year},
                    role=role,
                    status=status,
                    project_name=project,
                    segments=[seg.seg_id],
                    evidence=[ev],
                    source_links=links,
                    note=note,
                )

    _attach_interviews(claims, documents, graph)
    return sorted(claims.values(), key=lambda c: c.claim_id)


def _promote_role(claim: Claim, role: str) -> None:
    """同一行动多篇发稿时，以最具体的角色为准。"""
    rank = {
        "negated": 0,
        "intent": 1,
        "commitment": 2,
        "referenced_peer": 2,
        "implemented": 3,
    }
    if rank.get(role, 1) > rank.get(claim.role, 1):
        claim.role = role


def _attach_interviews(
    claims: dict[tuple[str, str, str], Claim] | list[Claim],
    documents: dict[str, dict],
    graph: ProvenanceGraph,
) -> None:
    """采访纪要中的明确核实结论并入对应场址候选。

    只作用于采访点名的场址与句中点名的做法；采访明确核实的动作才升级为
    interview_verified（研究规则 R3），否定句不升级。
    """
    claim_list = list(claims.values()) if isinstance(claims, dict) else claims
    by_site: dict[str, list[Claim]] = {}
    for claim in claim_list:
        by_site.setdefault(claim.site, []).append(claim)

    for note in documents.values():
        if note["类别"] != "采访":
            continue
        for seg in split_document(note["id"], note["文字"]):
            seg_places = set(PLACE_PATTERN.findall(seg.text))
            negative = any(
                marker in seg.text for marker in ("不是", "未", "没有")
            )
            for place in seg_places:
                for claim in by_site.get(place, ()):
                    # 采访否定句可能没有做法词（"X 与 Y 不是同一项目"），
                    # 仅当项目专名/设施词与候选对象对得上才关联，避免外溢。
                    claim_facility = claim.project_name.split("-", 1)[-1]
                    same_object = (
                        claim_facility in seg.text
                        or (
                            claim.practice == "回用"
                            and any(
                                word in seg.text
                                for word in (
                                    "回用一号", "青瓦", "换热",
                                    "供冷", "回用",
                                )
                            )
                        )
                    )
                    if not same_object:
                        continue
                    claim.evidence.append(
                        Evidence(
                            source_id=note["id"],
                            seg_id=seg.seg_id,
                            quote=seg.text,
                            kind="interview",
                        )
                    )
                    # 正面陈述本场设施/动作（含"独立采购"等措辞）时，
                    # 按 R3 升级为采访核实；否定句只附证据不升级。
                    if not negative and (
                        "独立" in seg.text
                        or any(
                            marker in seg.text
                            for marker in ("试运", "运行", "采购")
                        )
                    ):
                        claim.status = "interview_verified"
                        claim.note = (
                            f"采访 {note['id']} 明确核实本场 {claim.practice} "
                            "动作；与他场的同项目假设已被采访否定"
                        )
                    elif negative:
                        claim.note = (
                            f"采访 {note['id']} 否定与他场同项目，"
                            "本场候选保留独立身份"
                        )
