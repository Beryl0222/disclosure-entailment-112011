"""访查窗口选样、覆盖核算与余量说明。

规则对应 research.json：

- 先保明确（已确认/已完成）且仍可核实的预约，再用开放窗口最多补覆盖缺口；
- 本轮总次数与同集团场址数有上限，已完成访问计入；
- 只安排登记可接待、且窗口本身可接待的场址；
- 同一实际行动反复发稿只算一次覆盖；同样覆盖优先更早开放的窗口；
- 一次到访可核实多项做法；同场址补证可并入已有预约，不占其他企业名额。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .claims import Claim

ROUND_LIMIT = 3
GROUP_SITE_LIMIT = 2


@dataclass(frozen=True)
class Window:
    visit_id: str
    date: str
    site: str
    person: str
    status: str
    goal: str
    bookable: bool
    """场址登记可接待且窗口未被拒绝。"""
    block_reason: str


@dataclass
class PlannedVisit:
    visit_id: str
    date: str
    site: str
    person: str
    status: str
    goal: str
    decision: str
    """keep 保留预约 / add 本轮新增 / merge 并入已有预约 /
    blocked 不可安排 / leftover 未能排入。"""
    reason: str
    covers: set[tuple[str, int, str]] = field(default_factory=set)
    claim_ids: list[str] = field(default_factory=list)
    verified_claim_ids: list[str] = field(default_factory=list)
    """已完成访查实际核实到的候选。"""
    merged_into: str | None = None


@dataclass
class Leftover:
    visit_id: str | None
    site: str
    reason_code: str
    """source_pending 来源待区分 / already_covered 同一行动已有覆盖 /
    no_window 独立但没有合适窗口 / not_receptive 无法接触 /
    no_candidate 缺口无候选。"""
    detail: str


@dataclass
class CellGap:
    industry: str
    year: int
    practice: str
    state: str
    """covered 已安排核实 / candidate 有候选待窗口 / empty 无任何候选。"""
    claim_ids: list[str] = field(default_factory=list)


@dataclass
class Plan:
    visits: list[PlannedVisit]
    leftovers: list[Leftover]
    cells: list[CellGap]
    kept_visits: list[str]
    added_visits: list[str]
    merged_visits: list[str]

    def find(self, visit_id: str) -> PlannedVisit:
        return next(v for v in self.visits if v.visit_id == visit_id)


def parse_windows(
    visits: list[dict], actors: dict[str, dict]
) -> list[Window]:
    windows: list[Window] = []
    for row in visits:
        actor = next(
            (a for a in actors.values() if a["场址"] == row["场址"]), None
        )
        receptive = bool(actor and actor["可接待"])
        refused = "未允许" in row["目标"] or "不可" in row["目标"]
        bookable = receptive and not refused
        reason = ""
        if not receptive:
            reason = "登记为不可接待"
        elif refused:
            reason = "窗口记录显示外部访查未获允许"
        windows.append(
            Window(
                visit_id=row["id"],
                date=row["日期"],
                site=row["场址"],
                person=row["人员"],
                status=row["状态"],
                goal=row["目标"],
                bookable=bookable,
                block_reason=reason,
            )
        )
    return windows


def _site_industry(actors: dict[str, dict], site: str) -> str:
    actor = next((a for a in actors.values() if a["场址"] == site), None)
    return actor["行业"] if actor else ""


def _site_group(actors: dict[str, dict], site: str) -> str:
    actor = next((a for a in actors.values() if a["场址"] == site), None)
    return actor["集团"] if actor else ""


def _site_claims(site: str, claims: list[Claim]) -> list[Claim]:
    return [claim for claim in claims if claim.site == site]


def _verifiable_claims(site: str, claims: list[Claim]) -> list[Claim]:
    """该场址仍可现场核实的候选：排除未开展项、已现场核实项与引用同行内容。"""
    return [
        claim
        for claim in _site_claims(site, claims)
        if claim.role not in {"negated", "referenced_peer"}
        and claim.status != "site_verified"
    ]


# 访查目标中能对应到做法类型的措辞（比披露关键词更贴近日志语言）
GOAL_PRACTICE_TERMS: dict[str, tuple[str, ...]] = {
    "回用": ("青瓦", "回用", "供冷", "回收设施", "回收装置", "冷凝"),
    "巡检": ("巡检", "台账"),
    "能量回收": ("蒸汽", "冷凝水", "换热", "能量"),
}


def _goal_mentions(clause: str, practice: str) -> bool:
    return any(term in clause for term in GOAL_PRACTICE_TERMS[practice])


def apply_site_verifications(
    visits: list[dict], claims: list[Claim]
) -> dict[str, list[str]]:
    """按已完成访查目标登记现场核实结果（R3：只认明确核实的动作）。

    目标中的否定措辞（如"未见巡检台账"）不登记核实。
    返回 ``{visit_id: [claim_id,...]}`` 并把候选状态置为 site_verified。
    """
    verified: dict[str, list[str]] = {}
    for row in visits:
        if row["状态"] != "已完成":
            continue
        hit: list[str] = []
        goal = row["目标"]
        for clause in re.split(r"[。；;]", goal):
            negative = any(
                marker in clause for marker in ("未见", "未", "没有", "无")
            )
            if negative:
                continue
            for claim in claims:
                if claim.site != row["场址"]:
                    continue
                if _goal_mentions(clause, claim.practice):
                    claim.status = "site_verified"
                    hit.append(claim.claim_id)
        verified[row["id"]] = sorted(set(hit))
    return verified


def build_plan(
    visits: list[dict],
    actors: dict[str, dict],
    claims: list[Claim],
    research_cells: list[tuple[str, int, str]],
) -> Plan:
    windows = parse_windows(visits, actors)
    planned: list[PlannedVisit] = []
    leftovers: list[Leftover] = []

    verified = apply_site_verifications(visits, claims)
    fixed = [w for w in windows if w.status in {"已确认", "已完成"}]
    opens = sorted(
        (w for w in windows if w.status == "开放"),
        key=lambda w: (w.date, w.visit_id),
    )

    used_visits = 0
    group_sites: dict[str, set[str]] = {}

    def count_site(site: str) -> None:
        group = _site_group(actors, site)
        group_sites.setdefault(group, set()).add(site)

    # 1) 已完成/已确认预约：先保明确且仍可核实的安排。
    for win in fixed:
        site_all = _site_claims(win.site, claims)
        verifiable = _verifiable_claims(win.site, claims)
        if win.status == "已完成":
            decision = "keep"
            reason = "已完成采访，保留实际场址与核实范围"
            used_visits += 1
            count_site(win.site)
            # 已完成到访：覆盖以该场址全部候选所落格子为准（含已现场核实项），
            # 已核实项不再列为"仍可核实"，但覆盖保留。
            visit_covers = _cells_of(win.site, site_all, actors)
            visit_claims = [
                c.claim_id
                for c in site_all
                if c.role not in {"negated", "referenced_peer"}
            ]
        else:
            if verifiable and win.bookable:
                decision = "keep"
                reason = "已确认预约且至少一项独立研究目标仍可核实"
                used_visits += 1
                count_site(win.site)
            else:
                decision = "leftover"
                reason = "已确认预约已无独立可核实目标，交负责人调整"
                leftovers.append(
                    Leftover(win.visit_id, win.site, "already_covered", reason)
                )
            visit_covers = _cells_of(win.site, verifiable, actors)
            visit_claims = [c.claim_id for c in verifiable]
        planned.append(
            PlannedVisit(
                win.visit_id, win.date, win.site, win.person, win.status,
                win.goal, decision, reason,
                covers=visit_covers,
                claim_ids=visit_claims,
                verified_claim_ids=verified.get(win.visit_id, []),
            )
        )

    covered_cells: set[tuple[str, int, str]] = set()
    for pv in planned:
        if pv.decision == "keep":
            covered_cells |= pv.covers

    # 2) 同场址开放窗口先尝试并入已有预约（补新证明，不占名额）。
    fixed_sites = {w.site for w in fixed}
    remaining_opens: list[Window] = []
    for win in opens:
        if not win.bookable:
            planned.append(
                PlannedVisit(
                    win.visit_id, win.date, win.site, win.person, win.status,
                    win.goal, "blocked", win.block_reason,
                )
            )
            leftovers.append(
                Leftover(
                    win.visit_id, win.site, "not_receptive", win.block_reason
                )
            )
            continue
        if win.site in fixed_sites:
            target = next(pv for pv in planned if pv.site == win.site)
            known = set(target.claim_ids)
            new_claims = [
                c for c in _verifiable_claims(win.site, claims)
                if c.claim_id not in known
            ]
            planned.append(
                PlannedVisit(
                    win.visit_id, win.date, win.site, win.person, win.status,
                    win.goal, "merge",
                    f"同场址补证并入已有预约 {target.visit_id}，"
                    "不占其他企业名额",
                    covers=_cells_of(win.site, new_claims, actors),
                    claim_ids=[c.claim_id for c in new_claims],
                    merged_into=target.visit_id,
                )
            )
            target.claim_ids = sorted(
                set(target.claim_ids) | {c.claim_id for c in new_claims}
            )
            target.covers |= _cells_of(win.site, new_claims, actors)
            covered_cells |= target.covers
            continue
        remaining_opens.append(win)

    # 3) 以研究格子为中心补缺口：按规定顺序处理尚未覆盖的格子，
    #    能覆盖该格子的窗口中取最早开放者（R1）；一次到访覆盖其全部格子。
    site_windows: dict[str, list[Window]] = {}
    for win in remaining_opens:
        site_windows.setdefault(win.site, []).append(win)
    site_cells = {
        site: frozenset(
            _cells_of(site, _verifiable_claims(site, claims), actors)
        )
        for site in site_windows
    }
    chosen_visit_ids: set[str] = set()

    def earliest_window(site: str) -> Window:
        return sorted(site_windows[site], key=lambda w: (w.date, w.visit_id))[0]

    for cell in list(research_cells):
        if cell in covered_cells:
            continue
        if used_visits >= ROUND_LIMIT:
            break  # 其余格子在第 4 步统一登记余量
        covering_sites = sorted(
            site for site, cells in site_cells.items() if cell in cells
        )
        if not covering_sites:
            continue
        candidates = [earliest_window(site) for site in covering_sites]
        candidates.sort(key=lambda w: (w.date, w.visit_id))
        for win in candidates:
            if win.visit_id in chosen_visit_ids:
                covered_cells |= site_cells[win.site]
                break
            group = _site_group(actors, win.site)
            if len(group_sites.get(group, set())) >= GROUP_SITE_LIMIT:
                leftovers.append(
                    Leftover(
                        win.visit_id, win.site, "no_window",
                        f"集团 {group} 本轮实地场址已达 {GROUP_SITE_LIMIT} 个上限",
                    )
                )
                continue
            site_claims = _verifiable_claims(win.site, claims)
            new_cells = site_cells[win.site] - covered_cells
            planned.append(
                PlannedVisit(
                    win.visit_id, win.date, win.site, win.person, win.status,
                    win.goal, "add",
                    f"按最早开放窗口补研究格子 {cell}，同次到访另覆盖 "
                    f"{len(new_cells) - 1} 个格子",
                    covers=set(site_cells[win.site]),
                    claim_ids=[c.claim_id for c in site_claims],
                )
            )
            chosen_visit_ids.add(win.visit_id)
            covered_cells |= site_cells[win.site]
            used_visits += 1
            count_site(win.site)
            break

    # 未入选的开放窗口逐一说明原因
    for win in remaining_opens:
        if win.visit_id in chosen_visit_ids:
            continue
        if any(
            item.visit_id == win.visit_id and item.reason_code == "no_window"
            for item in leftovers
        ):
            continue
        rep = earliest_window(win.site)
        if rep.visit_id != win.visit_id:
            leftovers.append(
                Leftover(
                    win.visit_id, win.site, "already_covered",
                    f"同覆盖窗口 {rep.visit_id} 日期更早，本窗口不另占名额",
                )
            )
        else:
            leftovers.append(
                Leftover(
                    win.visit_id, win.site, "no_window",
                    "本轮访查次数或集团场址上限已满，无合适窗口",
                )
            )

    # 4) 研究格子覆盖盘点；有候选却排不进的，登记为没有合适窗口。
    cells = _gap_board(research_cells, claims, actors, covered_cells)
    placed_sites = {pv.site for pv in planned if pv.decision in {"keep", "add"}}
    for cell in cells:
        if cell.state != "candidate":
            continue
        related_sites = {
            claim.site
            for claim in claims
            if _site_industry(actors, claim.site) == cell.industry
            and cell.year in claim.years
            and claim.practice == cell.practice
            and claim.role not in {"negated", "referenced_peer"}
        }
        for site in sorted(related_sites - placed_sites):
            if _is_blocked(planned, site):
                leftovers.append(
                    Leftover(
                        None, site, "not_receptive",
                        f"独立候选可补 {cell.industry}/{cell.year}/"
                        f"{cell.practice}，但团队无法接触该工厂",
                    )
                )
            else:
                leftovers.append(
                    Leftover(
                        None, site, "no_window",
                        f"独立候选可补 {cell.industry}/{cell.year}/"
                        f"{cell.practice}，但本轮没有合适窗口",
                    )
                )

    return Plan(
        visits=sorted(planned, key=lambda v: (v.date, v.visit_id)),
        leftovers=leftovers,
        cells=cells,
        kept_visits=[v.visit_id for v in planned if v.decision == "keep"],
        added_visits=[v.visit_id for v in planned if v.decision == "add"],
        merged_visits=[v.visit_id for v in planned if v.decision == "merge"],
    )


def _is_blocked(planned: list[PlannedVisit], site: str) -> bool:
    return any(
        pv.site == site and pv.decision == "blocked" for pv in planned
    )


def _cells_of(
    site: str, site_claims: list[Claim], actors: dict[str, dict]
) -> set[tuple[str, int, str]]:
    industry = _site_industry(actors, site)
    actor = next((a for a in actors.values() if a["场址"] == site), None)
    if actor is None or not actor["可接待"]:
        return set()  # 团队无法接触的工厂不产生覆盖
    cells: set[tuple[str, int, str]] = set()
    for claim in site_claims:
        for year in claim.years:
            cells.add((industry, year, claim.practice))
    return cells


def _gap_board(
    research_cells: list[tuple[str, int, str]],
    claims: list[Claim],
    actors: dict[str, dict],
    covered_cells: set[tuple[str, int, str]],
) -> list[CellGap]:
    board: list[CellGap] = []
    for industry, year, practice in research_cells:
        related = [
            claim.claim_id
            for claim in claims
            if _site_industry(actors, claim.site) == industry
            and year in claim.years
            and claim.practice == practice
            and claim.role not in {"negated", "referenced_peer"}
            and _receptive(actors, claim.site)
        ]
        if (industry, year, practice) in covered_cells:
            state = "covered"
        elif related:
            state = "candidate"
        else:
            state = "empty"
        board.append(CellGap(industry, year, practice, state, related))
    return board


def _receptive(actors: dict[str, dict], site: str) -> bool:
    actor = next((a for a in actors.values() if a["场址"] == site), None)
    return bool(actor and actor["可接待"])
