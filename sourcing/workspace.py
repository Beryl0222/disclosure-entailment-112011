"""工作区：装配资料、接入新证据并再规划。

新证据有两类：

- 更早的范文/底文：改变文字来源认定（template_reuse），但不改变已完成访查；
- 采访发现"总部与分公司写的是两座厂"：否定同一项目假设，修正尚未出发的
  访查目标，已完成采访保留实际场址与所核范围，并暴露新的覆盖缺口。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .claims import Claim, extract_claims
from .provenance import ProvenanceGraph, build_graph
from .textmodel import load_documents
from .visits import Plan, build_plan


@dataclass
class Workspace:
    documents: dict[str, dict]
    actors: dict[str, dict]
    research_rows: list[dict]
    visit_rows: list[dict]
    graph: ProvenanceGraph
    claims: list[Claim]
    plan: Plan
    change_log: list[str]

    def research_cells(self) -> list[tuple[str, int, str]]:
        return parse_research_cells(self.research_rows)


def load_workspace(data_dir: str | Path) -> Workspace:
    data_dir = Path(data_dir)
    documents = load_documents(data_dir / "texts.json")
    actors = load_documents(data_dir / "actors.json")
    research_rows = list(load_documents(data_dir / "research.json").values())
    visit_rows = list(load_documents(data_dir / "visits.json").values())

    graph = build_graph(documents, actors)
    claims = extract_claims(documents, actors, graph)
    plan = build_plan(
        visit_rows, actors, claims, parse_research_cells(research_rows)
    )
    return Workspace(
        documents=documents,
        actors=actors,
        research_rows=research_rows,
        visit_rows=visit_rows,
        graph=graph,
        claims=claims,
        plan=plan,
        change_log=[],
    )


def parse_research_cells(
    research_rows: list[dict],
) -> list[tuple[str, int, str]]:
    """从研究规定原文解析行业×年度×做法格子，保持规定顺序。"""
    industries = ("装配", "材料")
    years = (2024, 2025)
    practice_terms = {
        "回用": "回用",
        "巡检": "巡检",
        "能量回收": "能量回收",
    }
    practices: list[str] = []
    for row in research_rows:
        for label in practice_terms:
            if label in row["原文"] and label not in practices:
                practices.append(label)
    return [
        (industry, year, practice)
        for industry in industries
        for year in years
        for practice in practices
    ]


def revise(
    workspace: Workspace,
    *,
    new_documents: list[dict] | None = None,
    interview_documents: list[dict] | None = None,
) -> Workspace:
    """接入新范文或采访后重建分析，保留已完成访查并记录变更。"""
    change_log: list[str] = []
    documents = dict(workspace.documents)

    for doc in new_documents or []:
        if doc["id"] in documents:
            raise ValueError(f"文档编号已存在：{doc['id']}")
        documents[doc["id"]] = doc
        if doc["类别"] == "范文":
            change_log.append(
                f"登记更早范文 {doc['id']}（发布 {doc['发布']}）："
                "相关文字改记为范文复用，已完成访查不变"
            )

    for doc in interview_documents or []:
        if doc["id"] in documents:
            raise ValueError(f"文档编号已存在：{doc['id']}")
        documents[doc["id"]] = doc
        change_log.append(
            f"登记采访 {doc['id']}：按采访结论修正关系与未出发访查目标，"
            "已完成访查保留实际场址与所核范围"
        )

    old_plan = workspace.plan
    graph = build_graph(documents, workspace.actors)
    claims = extract_claims(documents, workspace.actors, graph)
    plan = build_plan(
        workspace.visit_rows,
        workspace.actors,
        claims,
        parse_research_cells(workspace.research_rows),
    )

    _diff_visits(old_plan, plan, change_log)
    _diff_coverage(old_plan, plan, change_log)
    workspace.documents = documents
    workspace.graph = graph
    workspace.claims = claims
    workspace.plan = plan
    workspace.change_log = workspace.change_log + change_log
    return workspace


def _diff_visits(old: Plan, new: Plan, log: list[str]) -> None:
    old_by_id = {v.visit_id: v for v in old.visits}
    for pv in new.visits:
        before = old_by_id.get(pv.visit_id)
        if before is None:
            continue
        if before.decision != pv.decision:
            log.append(
                f"访查 {pv.visit_id}（{pv.site}）安排由 {before.decision} "
                f"变为 {pv.decision}：{pv.reason}"
            )
        if before.covers != pv.covers:
            added = sorted(pv.covers - before.covers)
            removed = sorted(before.covers - pv.covers)
            if added:
                log.append(f"访查 {pv.visit_id} 新增覆盖：{added}")
            if removed:
                log.append(f"访查 {pv.visit_id} 移出覆盖：{removed}")


def _diff_coverage(old: Plan, new: Plan, log: list[str]) -> None:
    def board(plan: Plan) -> dict[tuple[str, int, str], str]:
        return {(c.industry, c.year, c.practice): c.state for c in plan.cells}

    before, after = board(old), board(new)
    for cell, state in after.items():
        if before.get(cell) != state:
            log.append(f"研究格子 {cell} 状态：{before.get(cell)} → {state}")


def export_grouping(workspace: Workspace, path: str | Path) -> Path:
    """导出可从访查对象回溯原段、独立内容与来源确认的分组选样材料。"""
    payload = {
        "claims": [_claim_dict(workspace, claim) for claim in workspace.claims],
        "visits": [_visit_dict(pv) for pv in workspace.plan.visits],
        "leftovers": [vars(item) for item in workspace.plan.leftovers],
        "coverage": [vars(cell) for cell in workspace.plan.cells],
        "change_log": workspace.change_log,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def _claim_dict(workspace: Workspace, claim: Claim) -> dict:
    return {
        "claim_id": claim.claim_id,
        "site": claim.site,
        "actor": claim.actor_id,
        "industry": next(
            (a["行业"] for a in workspace.actors.values()
             if a["场址"] == claim.site),
            "",
        ),
        "practice": claim.practice,
        "years": sorted(claim.years),
        "role": claim.role,
        "status": claim.status,
        "project": claim.project_name,
        "segments": [
            {
                "seg_id": seg_id,
                "text": workspace.graph.segments[seg_id].text,
            }
            for seg_id in claim.segments
        ],
        "evidence": [vars(ev) for ev in claim.evidence],
        "source_links": [
            _link_dict(workspace, link_id)
            for link_id in claim.source_links
        ],
        "note": claim.note,
    }


def _find_link(workspace: Workspace, link_id: str):
    return next(
        (link for link in workspace.graph.links if link.link_id == link_id),
        None,
    )


def _link_dict(workspace: Workspace, link_id: str) -> dict:
    link = _find_link(workspace, link_id)
    if link is None:
        return {"link_id": link_id, "missing": True}
    sim = link.similarity
    return {
        "link_id": link.link_id,
        "kind": link.kind,
        "status": link.status,
        "basis": link.basis,
        "left": link.left,
        "right": link.right,
        "evidence": list(link.evidence),
        "slots": list(sim.replaced_slots) if sim else [],
    }


def _visit_dict(pv) -> dict:
    return {
        "visit_id": pv.visit_id,
        "date": pv.date,
        "site": pv.site,
        "person": pv.person,
        "status": pv.status,
        "decision": pv.decision,
        "reason": pv.reason,
        "covers": sorted(pv.covers),
        "claim_ids": pv.claim_ids,
        "verified_claim_ids": pv.verified_claim_ids,
        "merged_into": pv.merged_into,
        "goal": pv.goal,
    }
