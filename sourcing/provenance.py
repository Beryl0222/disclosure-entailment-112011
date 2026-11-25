"""句段来源关系与同源传递。

关系类型（``kind``）：

- ``template_reuse``  范文/园区底文复用（含改写与槽位替换）
- ``citation``        文字中明确引用他人做法或项目代号
- ``same_project``    同一实际行动/项目被不同主体分别描述
- ``text_only_reuse`` 仅文字照抄（采访等证据表明行动彼此独立）
- ``shared_terms``    只有术语相似，不能证实同源

关系状态（``status``）：``proposed``（工具提议，待研究员判断）、
``confirmed``（有底文或采访等证据）、``refuted``（证据否定同源）。

同源传递规则：``template_reuse`` 与 ``same_project`` 各自只在能解释重复内容或
同一项目的同类已确认边之间传递；通用范文边不会把两个独立项目连成一家；
``text_only_reuse``/``shared_terms`` 不参与传递。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from .textmodel import Segment, Similarity, compare, split_document

# 综合相似度阈值（四项指标等权，见 Similarity.score）
TEMPLATE_PARAPHRASE = 0.30
WORDING_MATCH = 0.22

REFERENCE_INTENT = ("借鉴", "参照", "参考", "引用", "推给", "推广", "照着写", "照抄")
PROJECT_TERMS = ("青瓦", "回用一号")
PLACE_TERMS = ("南站", "北站", "西站", "汀湾", "长塘")
# 具体设施词共现才足以把两段描述联系到同一设施；"回收"过宽，不计入。
FACILITY_TERMS = ("废水", "供冷", "换热", "回用", "青瓦")
TRANSITIVE_KINDS = frozenset({"template_reuse", "same_project"})


@dataclass(frozen=True)
class Link:
    """两个句段之间的一条来源关系。"""

    link_id: str
    left: str
    right: str
    kind: str
    status: str
    basis: str
    similarity: Similarity | None = None
    evidence: tuple[str, ...] = field(default_factory=tuple)
    """支撑该关系的文档 id（如采访纪要或更早范文）。"""

    def endpoints(self) -> frozenset[str]:
        return frozenset((self.left, self.right))


@dataclass
class ProvenanceGraph:
    documents: dict[str, dict]
    actors: dict[str, dict]
    segments: dict[str, Segment]
    links: list[Link]

    def links_for(self, seg_id: str) -> list[Link]:
        return [link for link in self.links if seg_id in link.endpoints()]

    def confirm(self, link_id: str, basis: str, evidence: str) -> Link:
        """研究员补录底文或确认某一段关系。"""
        for i, link in enumerate(self.links):
            if link.link_id == link_id:
                updated = Link(
                    link_id=link.link_id,
                    left=link.left,
                    right=link.right,
                    kind=link.kind,
                    status="confirmed",
                    basis=basis,
                    similarity=link.similarity,
                    evidence=tuple(sorted(set(link.evidence) | {evidence})),
                )
                self.links[i] = updated
                return updated
        raise KeyError(f"关系不存在：{link_id}")

    def refute(self, link_id: str, basis: str, evidence: str) -> Link:
        for i, link in enumerate(self.links):
            if link.link_id == link_id:
                updated = Link(
                    link_id=link.link_id,
                    left=link.left,
                    right=link.right,
                    kind=link.kind,
                    status="refuted",
                    basis=basis,
                    similarity=link.similarity,
                    evidence=tuple(sorted(set(link.evidence) | {evidence})),
                )
                self.links[i] = updated
                return updated
        raise KeyError(f"关系不存在：{link_id}")

    def _active_edges(self, kind: str) -> dict[str, set[str]]:
        adj: dict[str, set[str]] = {}
        for link in self.links:
            if link.kind == kind and link.status == "confirmed":
                adj.setdefault(link.left, set()).add(link.right)
                adj.setdefault(link.right, set()).add(link.left)
        return adj

    def explain_path(self, left: str, right: str, kind: str) -> list[str]:
        """返回可解释两端同源的同类已确认边路径；不存在则为空。

        路径上每条边都必须确实解释重复内容（template_reuse）或同一项目
        （same_project），通用文字边不会跨项目传递。
        """
        if kind not in TRANSITIVE_KINDS:
            return []
        adj = self._active_edges(kind)
        if left == right:
            return [left]
        queue = [(left, [left])]
        seen = {left}
        while queue:
            node, path = queue.pop(0)
            for nxt in sorted(adj.get(node, ())):
                if nxt in seen:
                    continue
                new_path = path + [nxt]
                if nxt == right:
                    return new_path
                seen.add(nxt)
                queue.append((nxt, new_path))
        return []

    def wording_family(self, seg_id: str) -> set[str]:
        """范文/底文复用族：已确认的 template_reuse 闭包。"""
        return self._closure(seg_id, "template_reuse")

    def project_family(self, seg_id: str) -> set[str]:
        """同一项目描述族：已确认的 same_project 闭包。"""
        return self._closure(seg_id, "same_project")

    def _closure(self, seg_id: str, kind: str) -> set[str]:
        adj = self._active_edges(kind)
        result = {seg_id}
        queue = [seg_id]
        while queue:
            node = queue.pop()
            for nxt in adj.get(node, ()):
                if nxt not in result:
                    result.add(nxt)
                    queue.append(nxt)
        return result

    def alternatives(self, seg_id: str) -> list[dict[str, object]]:
        """未证实同源关系的两种解释及其对候选合并的影响。"""
        out: list[dict[str, object]] = []
        for link in self.links_for(seg_id):
            if link.status != "proposed":
                continue
            out.append(
                {
                    "link_id": link.link_id,
                    "other": next(iter(link.endpoints() - {seg_id})),
                    "kind": link.kind,
                    "if_shared_source": "两端合并为同一来源/项目，只保留一份实践候选",
                    "if_independent": "两端各自保留独立实践候选，共享术语仅作出处对照",
                }
            )
        return out


def _all_segments(documents: dict[str, dict]) -> dict[str, Segment]:
    segments: dict[str, Segment] = {}
    for doc_id, doc in documents.items():
        for seg in split_document(doc_id, doc["文字"]):
            segments[seg.seg_id] = seg
    return segments


def _doc(documents: dict[str, dict], seg_id: str) -> dict:
    return documents[seg_id.split("-", 1)[0]]


def _actor_place(actors: dict[str, dict], actor_id: str) -> str:
    actor = actors.get(actor_id)
    return actor["场址"] if actor else ""


def _described_places(
    actors: dict[str, dict], doc: dict, text: str
) -> set[str]:
    """一段文字实际描述的场址：登记场址优先，集团/园区发稿按文字中的场址名。"""
    registered = _actor_place(actors, doc["主体"])
    if registered:
        return {registered}
    return {place for place in PLACE_TERMS if place in text}


def _shared_project_terms(left_text: str, right_text: str) -> list[str]:
    """能提示同源的词：只认项目代号；场址名仅用于同项目判定。

    不同场址恰好都写"废水/供冷"等行业术语，不构成同源证据。
    """
    return sorted(
        term for term in PROJECT_TERMS
        if term in left_text and term in right_text
    )


def _shared_anchors(left_text: str, right_text: str) -> list[str]:
    vocabulary = PROJECT_TERMS + PLACE_TERMS
    return sorted(
        term for term in vocabulary
        if term in left_text and term in right_text
    )


def _spans_distinct_sites(
    link: Link, documents: dict[str, dict], actors: dict[str, dict]
) -> bool:
    """两端是否落在不同场址：集团/园区发稿按句中文字点名的场址判断。"""
    places = set()
    for seg_id in (link.left, link.right):
        doc = documents[seg_id.split("-", 1)[0]]
        registered = _actor_place(actors, doc["主体"])
        if registered:
            places.add(registered)
            continue
        for place in PLACE_TERMS:
            if place in doc["文字"]:
                places.add(place)
    return len(places) > 1


def build_graph(
    documents: dict[str, dict], actors: dict[str, dict]
) -> ProvenanceGraph:
    """扫描全部句段对，提议可互相解释的来源关系。"""
    segments = _all_segments(documents)
    links: list[Link] = []
    counter = 0

    def add(left: Segment, right: Segment, kind: str, status: str,
            basis: str, sim: Similarity | None,
            evidence: tuple[str, ...] = ()) -> Link:
        nonlocal counter
        counter += 1
        link = Link(
            link_id=f"L{counter:03d}",
            left=left.seg_id,
            right=right.seg_id,
            kind=kind,
            status=status,
            basis=basis,
            similarity=sim,
            evidence=evidence,
        )
        links.append(link)
        return link

    template_ids = {
        doc_id for doc_id, doc in documents.items() if doc["类别"] == "范文"
    }
    interview_ids = [
        doc_id for doc_id, doc in documents.items() if doc["类别"] == "采访"
    ]

    for left, right in combinations(
        sorted(segments.values(), key=lambda s: s.seg_id), 2
    ):
        # 采访纪要是核实证据，不作为复用/引用关系的一方参与自动扫描
        ld0 = _doc(documents, left.seg_id)
        rd0 = _doc(documents, right.seg_id)
        if ld0["类别"] == "采访" or rd0["类别"] == "采访":
            continue
        sim = compare(left, right)
        lt, rt = left.text, right.text
        ld, rd = ld0, rd0
        left_is_template = ld["id"] in template_ids
        right_is_template = rd["id"] in template_ids
        shared_projects = _shared_project_terms(lt, rt)
        anchors = _shared_anchors(lt, rt)

        # 1) 范文复用：精确照抄直接确认；改写达到阈值则提议，记录替换槽位。
        if left_is_template != right_is_template and (
            sim.is_exact_copy or sim.score >= TEMPLATE_PARAPHRASE
        ):
            template_seg, other_seg = (
                (left, right) if left_is_template else (right, left)
            )
            if sim.is_exact_copy:
                add(
                    template_seg, other_seg, "template_reuse", "confirmed",
                    f"与范文 {template_seg.doc_id} 原文一致", sim,
                    (template_seg.doc_id,),
                )
            else:
                add(
                    template_seg, other_seg, "template_reuse", "proposed",
                    f"疑似改写范文 {template_seg.doc_id}，槽位："
                    f"{'、'.join(sim.replaced_slots)}",
                    sim, (template_seg.doc_id,),
                )
            continue

        # 2) 同一项目：共同出现场址/项目词且高相似；集团发稿可按文字中的
        #    场址归属到具体场址（集团发稿不必是行动所在地，但项目描述一致）。
        described_places = _described_places(actors, ld, lt) & _described_places(
            actors, rd, rt
        )
        if described_places and anchors and sim.score >= WORDING_MATCH:
            anchor_label = "、".join(anchors)
            add(
                left, right, "same_project", "confirmed",
                f"同一场址（{'、'.join(sorted(described_places))}）对同一项目"
                f"（{anchor_label}）的多篇发稿，行动只计一次",
                sim,
            )
            continue

        # 3) 明确引用：一端有引用意图且两端共享项目/场址词。
        cites = any(
            marker in text
            for text in (lt, rt)
            for marker in REFERENCE_INTENT
        )
        if cites and anchors:
            add(
                left, right, "citation", "proposed",
                "文字明确引用/参照他方做法，引用内容不计为本场行动",
                sim,
            )
            continue

        # 4) 仅有项目术语相似：同源待区分，保留两种解释。
        if shared_projects and sim.score >= WORDING_MATCH:
            add(
                left, right, "shared_terms", "proposed",
                f"共享项目术语（{'、'.join(shared_projects)}）但场址不同，"
                "无法证实同源，需补录底文或确认段落关系",
                sim,
            )

    counter = _apply_interview_findings(
        links, documents, interview_ids, segments, actors, counter
    )
    return ProvenanceGraph(
        documents=documents, actors=actors, segments=segments, links=links
    )


def _apply_interview_pair(
    links: list[Link],
    left_id: str,
    right_id: str,
    segments: dict[str, Segment],
    documents: dict[str, dict],
    actors: dict[str, dict],
    doc_id: str,
    denies_project: bool,
    says_text_copied: bool,
    counter: int,
) -> int:
    """把一份采访对一对句段的结论落到关系上，返回更新后的编号计数。"""
    existing = next(
        (
            link
            for link in links
            if link.endpoints() == frozenset((left_id, right_id))
        ),
        None,
    )
    target = existing
    if target is None:
        counter += 1
        target = Link(
            link_id=f"L{counter:03d}",
            left=left_id,
            right=right_id,
            kind="same_project",
            status="proposed",
            basis="采访点名的两座厂相关段落，按采访证据补建关系",
            similarity=compare(segments[left_id], segments[right_id]),
        )
        links.append(target)
    if not _spans_distinct_sites(target, documents, actors):
        return counter
    # 跨场址边按采访结论改判：补建边或工具先前提议的同项目假设都可被否定；
    # 已经是 shared_terms 的提议边则据采访补证据并标记为已否定同源。
    if denies_project and target.kind in {"same_project", "shared_terms"}:
        _rewrite(
            links, target, "shared_terms", "refuted",
            f"采访 {doc_id} 否定同一项目，分属两座厂",
            doc_id,
        )
    if says_text_copied and not any(
        link.link_id == f"{target.link_id}T" for link in links
    ):
        links.append(
            Link(
                link_id=f"{target.link_id}T",
                left=target.left,
                right=target.right,
                kind="text_only_reuse",
                status="confirmed",
                basis=(
                    f"采访 {doc_id} 确认计划文本被照着写，"
                    "两处行动各自独立"
                ),
                similarity=target.similarity,
                evidence=(doc_id,),
            )
        )
    return counter


def _apply_interview_findings(
    links: list[Link],
    documents: dict[str, dict],
    interview_ids: list[str],
    segments: dict[str, Segment],
    actors: dict[str, dict],
    counter: int,
) -> int:
    """把采访纪要中的明确结论落到关系状态上。

    采访只改变文字/项目关系的认定，不改变任何已完成访查的日期与场址。
    结论只作用于采访中点名的场址，不外推到其他企业。采访点名的两座厂即使
    措辞相似度未达自动阈值，也按采访证据显式补建关系边。返回更新后的编号计数。
    """

    def seg_place(seg_id: str) -> str:
        """句段实际指向的场址：先按句中唯一点名场址，否则回退登记场址。"""
        text = segments[seg_id].text
        named = [place for place in named_places if place in text]
        if len(named) == 1:
            return named[0]
        doc = documents[seg_id.split("-", 1)[0]]
        registered = _actor_place(actors, doc["主体"])
        if registered in named_places:
            return registered
        return named[0] if named else ""

    for doc_id in interview_ids:
        note = documents[doc_id]
        named_places = {p for p in PLACE_TERMS if p in note["文字"]}
        denies_project = "不是" in note["文字"] and named_places
        says_text_copied = any(
            marker in note["文字"]
            for marker in ("照着写", "照抄", "复用文本")
        )
        if not (denies_project or says_text_copied):
            continue

        full_pool = [
            seg_id
            for seg_id, seg in segments.items()
            if documents[seg_id.split("-", 1)[0]]["类别"]
            in {"披露", "集团披露"}
            and (
                any(place in seg.text for place in named_places)
                or _actor_place(
                    actors, documents[seg_id.split("-", 1)[0]]["主体"]
                )
                in named_places
            )
        ]
        # 采访点名的项目代号：代号话题只在含代号的句段间收窄配对，
        # 设施话题（废水/供冷等）仍在完整池中按同类设施词配对。
        interview_projects = [
            term
            for term in PROJECT_TERMS
            if term in note["文字"]
        ]
        code_pool = [
            seg_id
            for seg_id in full_pool
            if any(
                term in segments[seg_id].text for term in interview_projects
            )
        ]
        pool = full_pool
        interview_segments = [
            seg_id
            for seg_id, seg in segments.items()
            if documents[seg_id.split("-", 1)[0]]["类别"] == "采访"
            and any(place in seg.text for place in named_places)
        ]

        # 1) 项目代号句段之间：跨场址且两端共享同一项目代号才配对。
        for left_id, right_id in combinations(sorted(set(code_pool)), 2):
            if seg_place(left_id) == seg_place(right_id):
                continue
            lt, rt = segments[left_id].text, segments[right_id].text
            if not any(
                term in lt and term in rt
                for term in (*interview_projects, *PROJECT_TERMS)
            ):
                continue
            counter = _apply_interview_pair(
                links, left_id, right_id, segments, documents, actors,
                doc_id, denies_project, says_text_copied, counter,
            )

        # 2) 设施句段之间：同类具体设施词共现才配对（如南站/北站的废水供冷）。
        # 含任何项目代号的句段已在代号循环处理，设施循环不再触碰，避免外溢。
        facility_pool = [
            seg_id
            for seg_id in full_pool
            if not any(
                term in segments[seg_id].text for term in PROJECT_TERMS
            )
        ]
        for left_id, right_id in combinations(sorted(set(facility_pool)), 2):
            if seg_place(left_id) == seg_place(right_id):
                continue
            lt, rt = segments[left_id].text, segments[right_id].text
            specific_overlap = any(
                term in lt and term in rt for term in FACILITY_TERMS
            )
            if not specific_overlap:
                continue
            counter = _apply_interview_pair(
                links, left_id, right_id, segments, documents, actors,
                doc_id, denies_project, says_text_copied, counter,
            )

        # 采访句与披露句配对：采访句含项目代号时只认同代号披露段，
        # 否则按同类设施词配对，避免否定结论外溢到同场址其他做法。
        for interview_id in interview_segments:
            itext = segments[interview_id].text
            seg_projects = [
                term for term in PROJECT_TERMS if term in itext
            ]
            for disclosure_id in full_pool:
                if seg_place(interview_id) == seg_place(disclosure_id):
                    continue
                dtext = segments[disclosure_id].text
                if seg_projects:
                    if not any(term in dtext for term in seg_projects):
                        continue
                elif not any(
                    term in itext and term in dtext
                    for term in FACILITY_TERMS
                ):
                    continue
                counter = _apply_interview_pair(
                    links, disclosure_id, interview_id, segments, documents,
                    actors, doc_id, denies_project, says_text_copied, counter,
                )
    return counter


def _rewrite(
    links: list[Link], old: Link, kind: str, status: str, basis: str,
    evidence_id: str,
) -> None:
    idx = links.index(old)
    links[idx] = Link(
        link_id=old.link_id,
        left=old.left,
        right=old.right,
        kind=kind,
        status=status,
        basis=basis,
        similarity=old.similarity,
        evidence=tuple(sorted(set(old.evidence) | {evidence_id})),
    )
