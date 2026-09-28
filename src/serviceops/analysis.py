"""Turn the reporting layer into findings and recommendations.

Every sentence here is built from query results, so a change to the data or the SLA policy
changes the write-up with it rather than leaving stale numbers in prose.
"""
from __future__ import annotations

from . import queries as q
from .db import Database
from .taxonomy import CATEGORY_BY_NAME


def _rate(rows: list[dict], **match) -> tuple[float | None, int]:
    sel = [r for r in rows if all(r[k] == v for k, v in match.items())]
    tickets = sum(r["tickets"] for r in sel)
    breaches = sum(r["breaches"] or 0 for r in sel)
    return (round(100 * breaches / tickets, 1) if tickets else None), breaches


def findings(db: Database, f: q.Filters | None = None) -> dict:
    f = f or q.Filters()
    kpi = q.kpis(db, f)
    par = q.pareto(db, f)
    if len(par) < 2 or not kpi["sla_breaches"]:
        return {"kpis": kpi, "pareto": par, "focus": [], "recommendations": []}
    top = [r["label"] for r in par[:2]]
    top_share = par[1]["cumulative_share_pct"]
    top_volume = round(par[0]["share_of_volume_pct"] + par[1]["share_of_volume_pct"], 2)
    drv = q.drivers(db, f, top)
    subs = q.subcategories(db, f, top)
    wi = q.what_if(db, f, top)

    focus = []
    for name in top:
        rows = [r for r in drv if r["category"] == name]
        waited_rate, waited_breaches = _rate(rows, waited_on_third_party=1)
        clear_rate, _ = _rate(rows, waited_on_third_party=0)
        hop0, _ = _rate(rows, hop_bucket="0 hops")
        hop2, hop2_breaches = _rate(rows, hop_bucket="2+ hops")
        total_breaches = sum(r["breaches"] or 0 for r in rows)
        worst_sub = next((s for s in subs if s["category"] == name), None)
        focus.append({
            "category": name,
            "resolver_group": CATEGORY_BY_NAME[name].group,
            "wait_reason": CATEGORY_BY_NAME[name].wait_reason,
            "breaches": total_breaches,
            "breach_rate_waited_pct": waited_rate,
            "breach_rate_no_wait_pct": clear_rate,
            "share_of_breaches_waited_pct": round(100 * waited_breaches / total_breaches, 1)
            if total_breaches else None,
            "breach_rate_0_hops_pct": hop0,
            "breach_rate_2plus_hops_pct": hop2,
            "share_of_breaches_2plus_hops_pct": round(100 * hop2_breaches / total_breaches, 1)
            if total_breaches else None,
            "top_subcategory": worst_sub,
        })

    recs = []
    for item in focus:
        if item["category"] == "Access & Identity":
            recs.append({
                "title": "Take manager approval off the critical path for access requests",
                "evidence": (f"{item['share_of_breaches_waited_pct']}% of Access & Identity "
                             f"breaches sat waiting on approval. Tickets that waited breached "
                             f"{item['breach_rate_waited_pct']}% of the time, against "
                             f"{item['breach_rate_no_wait_pct']}% for those that did not."),
                "action": ("Publish pre-approved, role-based access bundles for the common "
                           "requests, and send an automatic reminder to the approver at 50% of "
                           "the SLA with escalation to their delegate at 75%."),
                "owner": "Identity & Access lead",
            })
        elif item["category"] == "Network & VPN":
            recs.append({
                "title": "Route connectivity tickets straight to Network Operations",
                "evidence": (f"Network & VPN tickets that changed hands two or more times "
                             f"breached {item['breach_rate_2plus_hops_pct']}% of the time, "
                             f"against {item['breach_rate_0_hops_pct']}% when the first group "
                             f"kept them; carrier waits pushed the rate to "
                             f"{item['breach_rate_waited_pct']}%."),
                "action": ("Add portal and email routing rules that send VPN, Wi-Fi and site "
                           "outage tickets to Network Operations on creation, and agree a "
                           "response-time clause with the carrier so vendor waits have a "
                           "contractual ceiling."),
                "owner": "Network Operations manager",
            })
        else:
            recs.append({
                "title": f"Review the {item['category']} queue",
                "evidence": f"{item['category']} holds a large share of breaches.",
                "action": "Examine hand-offs and third-party waits in this queue.",
                "owner": f"{item['resolver_group']} lead",
            })
    if wi:
        recs.append({
            "title": "Watch the two queues with an at-risk alert",
            "evidence": (f"If {top[0]} and {top[1]} breached at the rest of the desk's rate "
                         f"({wi['rest_breach_rate_pct']}%), about {wi['breaches_avoided']:,} "
                         f"breaches would not have happened and compliance would rise from "
                         f"{wi['current_compliance_pct']}% to {wi['what_if_compliance_pct']}%."),
            "action": ("Alert the resolver group when a ticket in either category reaches 75% "
                       "of its target, and review both queues weekly until their breach rate "
                       "is within two points of the desk average."),
            "owner": "Service desk manager",
        })

    headline = (f"{top[0]} and {top[1]} carry {top_volume:.0f}% of ticket volume but "
                f"{top_share:.0f}% of SLA breaches.")
    return {"kpis": kpi, "pareto": par, "top_categories": top,
            "top_share_of_breaches_pct": top_share, "top_share_of_volume_pct": top_volume,
            "headline": headline, "focus": focus, "what_if": wi, "recommendations": recs}
