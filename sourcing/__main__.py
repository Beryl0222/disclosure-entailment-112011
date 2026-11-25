"""命令行入口：浏览来源关系、行动候选、访查选样并导出分组材料。

示例：

    python3 -m sourcing links
    python3 -m sourcing claims --site 北站
    python3 -m sourcing plan
    python3 -m sourcing export -o reports/grouping.json
    python3 -m sourcing revise --interview data/new_interview.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .provenance import Link
from .textmodel import load_documents
from .workspace import Workspace, export_grouping, load_workspace, revise

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _link_dict(graph, link: Link) -> dict:
    sim = link.similarity
    return {
        "link_id": link.link_id,
        "kind": link.kind,
        "status": link.status,
        "left": link.left,
        "right": link.right,
        "basis": link.basis,
        "evidence": list(link.evidence),
        "slots": list(sim.replaced_slots) if sim else [],
        "score": round(sim.score, 3) if sim else None,
    }


def cmd_links(args: argparse.Namespace, ws: Workspace) -> None:
    rows = [_link_dict(ws.graph, link) for link in ws.graph.links]
    if args.seg:
        rows = [row for row in rows if args.seg in (row["left"], row["right"])]
    if args.kind:
        rows = [row for row in rows if row["kind"] == args.kind]
    _print_json(rows)


def cmd_alternatives(args: argparse.Namespace, ws: Workspace) -> None:
    _print_json(ws.graph.alternatives(args.seg))


def cmd_claims(args: argparse.Namespace, ws: Workspace) -> None:
    rows = []
    for claim in ws.claims:
        if args.site and claim.site != args.site:
            continue
        rows.append(
            {
                "claim_id": claim.claim_id,
                "site": claim.site,
                "actor": claim.actor_id,
                "practice": claim.practice,
                "years": sorted(claim.years),
                "role": claim.role,
                "status": claim.status,
                "project": claim.project_name,
                "segments": claim.segments,
                "source_links": claim.source_links,
                "evidence": [vars(ev) for ev in claim.evidence],
                "note": claim.note,
            }
        )
    _print_json(rows)


def cmd_plan(args: argparse.Namespace, ws: Workspace) -> None:
    payload = {
        "kept": ws.plan.kept_visits,
        "added": ws.plan.added_visits,
        "merged": ws.plan.merged_visits,
        "visits": [
            {
                "visit_id": v.visit_id,
                "date": v.date,
                "site": v.site,
                "status": v.status,
                "decision": v.decision,
                "reason": v.reason,
                "covers": sorted(v.covers),
                "claim_ids": v.claim_ids,
                "verified_claim_ids": v.verified_claim_ids,
                "merged_into": v.merged_into,
            }
            for v in ws.plan.visits
        ],
        "leftovers": [vars(x) for x in ws.plan.leftovers],
        "coverage": [vars(c) for c in ws.plan.cells],
    }
    _print_json(payload)


def cmd_export(args: argparse.Namespace, ws: Workspace) -> None:
    path = export_grouping(ws, args.output)
    print(f"已导出分组选样材料：{path}")


def cmd_revise(args: argparse.Namespace, ws: Workspace) -> None:
    new_docs = [
        row
        for path in args.template or []
        for row in load_documents(path).values()
    ]
    interviews = [
        row
        for path in args.interview or []
        for row in load_documents(path).values()
    ]
    revise(ws, new_documents=new_docs, interview_documents=interviews)
    _print_json({"change_log": ws.change_log})


def cmd_explain(args: argparse.Namespace, ws: Workspace) -> None:
    path = ws.graph.explain_path(args.left, args.right, args.kind)
    _print_json(
        {
            "kind": args.kind,
            "path": path,
            "transitive": bool(path),
            "note": (
                "仅沿能解释重复内容/同一项目的已确认同类边传递"
                if path else "无同源传递路径，不能据此合并独立实践"
            ),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="来源复用与访查选样工具")
    parser.add_argument("--data", default=str(DATA), help="资料目录")
    sub = parser.add_subparsers(dest="command", required=True)

    p_links = sub.add_parser("links", help="列出句段来源关系")
    p_links.add_argument("--seg", help="只看包含该句段编号的关系")
    p_links.add_argument("--kind", help="按关系类型过滤")
    p_links.set_defaults(func=cmd_links)

    p_alt = sub.add_parser(
        "alternatives", help="查看未证实同源关系的两种解释"
    )
    p_alt.add_argument("seg")
    p_alt.set_defaults(func=cmd_alternatives)

    p_claims = sub.add_parser("claims", help="列出场址行动候选")
    p_claims.add_argument("--site")
    p_claims.set_defaults(func=cmd_claims)

    p_plan = sub.add_parser("plan", help="查看访查选样与覆盖缺口")
    p_plan.set_defaults(func=cmd_plan)

    p_export = sub.add_parser("export", help="导出分组选样材料 JSON")
    p_export.add_argument("-o", "--output", required=True)
    p_export.set_defaults(func=cmd_export)

    p_revise = sub.add_parser(
        "revise", help="接入更早范文或新采访后再规划"
    )
    p_revise.add_argument(
        "--template", action="append", help="新范文 JSON 路径，可重复"
    )
    p_revise.add_argument(
        "--interview", action="append", help="新采访 JSON 路径，可重复"
    )
    p_revise.set_defaults(func=cmd_revise)

    p_explain = sub.add_parser("explain", help="检查同源传递路径")
    p_explain.add_argument("left")
    p_explain.add_argument("right")
    p_explain.add_argument(
        "--kind",
        choices=("template_reuse", "same_project"),
        default="same_project",
    )
    p_explain.set_defaults(func=cmd_explain)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    ws = load_workspace(args.data)
    args.func(args, ws)


if __name__ == "__main__":
    main()
