"""Generate the portfolio case study from a fresh build, so every number on the page is live.

usage:
    python scripts/build_case_study.py \
        ~/Desktop/nathan-portfolio/public/Project-Service-Ops-SLA.dc.html

The page borrows the portfolio's shared case-study stylesheet (the <style> block of
Project-Quant-Portfolio.dc.html next to the output file) and fills
scripts/case_study_template.html.
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from html import escape
from pathlib import Path

from serviceops import queries as q
from serviceops.db import Database
from serviceops.pipeline import build
from serviceops.simulate import N_TICKETS

ROOT = Path(__file__).resolve().parents[1]
BLUE, ORANGE = "#2a78d6", "#eb6834"  # validated categorical slots 1 and 2 (light surface)
GRID, TEXT, INK = "#e6e2db", "#686c71", "#16181a"
FONT = "font-family:'IBM Plex Mono',monospace"


def pct(v: float, d: int = 1) -> str:
    return f"{v:.{d}f}%"


def num(v: float) -> str:
    return f"{v:,.0f}"


def hours(v: float) -> str:
    return f"{v:.1f} h"


def share_chart(pareto: list[dict], top: set[str]) -> str:
    """Grouped horizontal bars: share of tickets vs share of breaches by category."""
    W, left, right, bh, gap, row = 760, 178, 64, 12, 3, 46
    H = 16 + row * len(pareto)
    hi = max(max(r["share_of_volume_pct"], r["share_of_breaches_pct"]) for r in pareto)
    hi = 35 if hi <= 35 else 40
    sx = lambda v: (W - left - right) * v / hi  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Share of tickets and share of SLA '
           f'breaches by category" style="width:100%;height:auto;{FONT}">']
    for t in range(0, hi + 1, 10):
        x = left + sx(t)
        out.append(f'<line x1="{x:.1f}" y1="6" x2="{x:.1f}" y2="{H - 4}" stroke="{GRID}"/>')
    for i, r in enumerate(pareto):
        y = 12 + i * row
        weight = ' font-weight="600"' if r["label"] in top else ""
        colour = INK if r["label"] in top else TEXT
        out.append(f'<text x="{left - 14}" y="{y + bh + 2}" text-anchor="end" font-size="12" '
                   f'fill="{colour}"{weight} font-family="IBM Plex Sans,sans-serif">'
                   f'{escape(r["label"])}</text>')
        for j, (key, colour) in enumerate([("share_of_volume_pct", BLUE),
                                           ("share_of_breaches_pct", ORANGE)]):
            yy = y + j * (bh + gap)
            w = sx(r[key])
            out.append(f'<rect x="{left}" y="{yy}" width="{w:.1f}" height="{bh}" rx="2" '
                       f'fill="{colour}"/>')
            out.append(f'<text x="{left + w + 6:.1f}" y="{yy + bh - 2}" font-size="11" '
                       f'fill="{TEXT}">{pct(r[key])}</text>')
    out.append(f'<line x1="{left}" y1="4" x2="{left}" y2="{H - 4}" stroke="#c9c4bb"/></svg>')
    return "\n".join(out)


def compliance_chart(monthly: list[dict], goal: float) -> str:
    """Monthly SLA compliance with the goal as a dashed reference line."""
    W, H, left, right, top, bottom = 760, 300, 52, 16, 16, 34
    lo, hi = 75, 95
    n = len(monthly)
    sx = lambda i: left + (W - left - right) * i / (n - 1)  # noqa: E731
    sy = lambda v: top + (H - top - bottom) * (hi - v) / (hi - lo)  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="SLA compliance by month against '
           f'the {goal:.0f}% goal" style="width:100%;height:auto;{FONT}">']
    for t in range(lo, hi + 1, 5):
        out.append(f'<line x1="{left}" y1="{sy(t):.1f}" x2="{W - right}" y2="{sy(t):.1f}" '
                   f'stroke="{GRID}"/><text x="{left - 8}" y="{sy(t) + 3.5:.1f}" '
                   f'text-anchor="end" font-size="10" fill="{TEXT}">{t}%</text>')
    for i, m in enumerate(monthly):
        if m["opened_month"].endswith(("-01", "-07")):
            label = ("Jan " if m["opened_month"].endswith("-01") else "Jul ") + \
                m["opened_month"][:4]
            out.append(f'<text x="{sx(i):.1f}" y="{H - 10}" text-anchor="middle" font-size="10" '
                       f'fill="{TEXT}">{label}</text>')
    out.append(f'<line x1="{left}" y1="{sy(goal):.1f}" x2="{W - right}" y2="{sy(goal):.1f}" '
               f'stroke="{TEXT}" stroke-dasharray="4 4"/><text x="{W - right}" '
               f'y="{sy(goal) - 6:.1f}" text-anchor="end" font-size="10" fill="{TEXT}">'
               f'Goal {goal:.0f}%</text>')
    pts = " ".join(f"{sx(i):.1f},{sy(max(lo, min(hi, m['sla_compliance_pct']))):.1f}"
                   for i, m in enumerate(monthly))
    out.append(f'<polyline points="{pts}" fill="none" stroke="{BLUE}" stroke-width="2" '
               f'stroke-linejoin="round"/>')
    worst = min(range(n), key=lambda i: monthly[i]["sla_compliance_pct"])
    w = monthly[worst]
    out.append(f'<circle cx="{sx(worst):.1f}" cy="{sy(w["sla_compliance_pct"]):.1f}" r="4" '
               f'fill="{BLUE}" stroke="#fff" stroke-width="2"/><text x="{sx(worst) + 8:.1f}" '
               f'y="{sy(w["sla_compliance_pct"]) + 14:.1f}" font-size="10.5" fill="{INK}">'
               f'{pct(w["sla_compliance_pct"])}</text>')
    out.append(f'<line x1="{left}" y1="{H - bottom}" x2="{W - right}" y2="{H - bottom}" '
               f'stroke="#c9c4bb"/></svg>')
    return "\n".join(out)


def main(target: Path) -> None:
    result = build(out_dir=ROOT / "output")
    db = Database(result.db_url)
    f, qr = result.findings, result.quality
    k = f["kpis"]
    everything = q.Filters()
    monthly = q.monthly(db, everything)
    priority = q.by_priority(db, everything)
    focus = {x["category"]: x for x in f["focus"]}
    ai, nv = focus["Access & Identity"], focus["Network & VPN"]
    wi = f["what_if"]
    worst_month = min(monthly, key=lambda m: m["sla_compliance_pct"])
    collected = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                               cwd=ROOT, capture_output=True, text=True).stdout
    tests = sum(1 for line in collected.splitlines() if "::" in line)

    pareto_rows = "\n".join(
        f'<tr class="{"win" if r["breach_rank"] <= 2 else ""}"><td>{r["breach_rank"]}. '
        f'{escape(r["label"])}</td><td>{num(r["tickets"])}</td><td>{num(r["breaches"])}</td>'
        f'<td>{pct(r["breach_rate_pct"])}</td><td>{pct(r["share_of_volume_pct"])}</td>'
        f'<td>{pct(r["share_of_breaches_pct"])}</td><td>{pct(r["cumulative_share_pct"])}</td></tr>'
        for r in f["pareto"])
    priority_rows = "\n".join(
        f'<tr><td>{p["priority_code"]} {p["priority"]}</td>'
        f'<td>{hours(p["resolution_target_hours"])}</td><td>{num(p["tickets"])}</td><td>{hours(p["avg_resolution_hours"])}</td>'
        f'<td>{pct(p["sla_compliance_pct"])}</td></tr>' for p in priority)
    check_rows = "\n".join(
        f'<tr><td>{c["id"]} &nbsp;{escape(c["name"])}</td><td>{c["dimension"]}</td>'
        f'<td>{c["action"]}</td><td>{num(c["rows"])}</td></tr>'
        for c in qr["checks"] if c["rows"])
    recs = "\n".join(
        f'<div class="ecard"><p class="eyebrow">Recommendation {i}</p><h3>{escape(r["title"])}'
        f'</h3><p>{escape(r["evidence"])}</p><p><b>Action.</b> {escape(r["action"])}</p>'
        f'<span class="stat">Owner: {escape(r["owner"])}</span></div>'
        for i, r in enumerate(f["recommendations"], 1))

    values = dict(
        simulated=num(N_TICKETS), rows_in=num(qr["rows_in"]),
        removed=num(qr["rows_removed"]), repaired=num(qr["rows_repaired"]),
        quarantined=num(qr["rows_quarantined"]), clean=num(qr["rows_clean"]),
        compliance=pct(k["sla_compliance_pct"]), response=pct(k["response_compliance_pct"]),
        breaches=num(k["sla_breaches"]), median=hours(k["median_resolution_hours"]),
        p90=hours(k["p90_resolution_hours"]), backlog=num(k["open_backlog"]),
        top_share=pct(f["top_share_of_breaches_pct"], 0),
        top_share_exact=pct(f["top_share_of_breaches_pct"]),
        top_volume=pct(f["top_share_of_volume_pct"], 0),
        focus_rate=pct(wi["focus_breach_rate_pct"]), rest_rate=pct(wi["rest_breach_rate_pct"]),
        what_if=pct(wi["what_if_compliance_pct"]), avoided=num(wi["breaches_avoided"]),
        ai_wait=pct(ai["breach_rate_waited_pct"]), ai_nowait=pct(ai["breach_rate_no_wait_pct"]),
        ai_wait_share=pct(ai["share_of_breaches_waited_pct"], 0),
        ai_hop2=pct(ai["breach_rate_2plus_hops_pct"]), ai_hop0=pct(ai["breach_rate_0_hops_pct"]),
        nv_wait=pct(nv["breach_rate_waited_pct"]), nv_nowait=pct(nv["breach_rate_no_wait_pct"]),
        nv_wait_share=pct(nv["share_of_breaches_waited_pct"], 0),
        nv_hop2=pct(nv["breach_rate_2plus_hops_pct"]), nv_hop0=pct(nv["breach_rate_0_hops_pct"]),
        worst_month=datetime.strptime(worst_month["opened_month"], "%Y-%m").strftime("%B %Y"),
        worst_value=pct(worst_month["sla_compliance_pct"]),
        share_chart=share_chart(f["pareto"], set(f["top_categories"])),
        compliance_chart=compliance_chart(monthly, 90.0),
        pareto_rows=pareto_rows, priority_rows=priority_rows, check_rows=check_rows,
        recs=recs, tests=tests,
    )
    style_src = target.parent / "Project-Quant-Portfolio.dc.html"
    style = re.search(r"<style>.*?</style>", style_src.read_text(), re.DOTALL).group(0)
    template = (ROOT / "scripts/case_study_template.html").read_text()
    target.write_text(template.format(style=style, **values))
    db.close()
    print(f"Wrote {target} ({f['headline']})")


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser())
