"""Simulate a service desk's ticket history, then export it the way a real ITSM tool would:
with duplicates, stale re-exports, blank fields, drifting labels and broken timelines.

The clean history is generated first so every defect injected afterwards is known exactly.
That answer key is what lets the tests prove the quality gate catches each defect class.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .taxonomy import (
    CATEGORIES,
    CHANNELS,
    DEPARTMENTS,
    END,
    GROUP_AGENTS,
    PRIORITIES,
    SITES,
    SNAPSHOT,
    START,
)

N_TICKETS = 50_000
SEED = 20260630

COLUMNS = ["ticket_id", "opened_at", "first_response_at", "resolved_at", "closed_at",
           "updated_at", "status", "priority", "category", "subcategory", "assignment_group",
           "assigned_agent", "channel", "department", "site", "reassignment_count", "reopened",
           "wait_reason"]

# Incidents that push volume above the normal pattern.
EVENTS = [
    # (start, end, category, extra tickets per day)
    ("2024-09-03", "2024-09-20", "Onboarding", 22),  # autumn hiring intake
    ("2025-02-10", "2025-02-14", "Network & VPN", 55),  # regional VPN concentrator failure
    ("2025-09-08", "2025-10-10", "Software", 30),  # Windows 11 migration wave
    ("2025-09-08", "2025-10-10", "Hardware", 14),
    ("2026-03-02", "2026-03-13", "Access & Identity", 26),  # MFA policy roll-out
]


def _pick(rng, pairs, n):
    labels, weights = zip(*pairs, strict=True)
    w = np.array(weights, dtype=float)
    return rng.choice(np.array(labels, dtype=object), size=n, p=w / w.sum())


def _daily_weights(days: pd.DatetimeIndex) -> np.ndarray:
    dow = days.dayofweek.to_numpy()
    w = np.where(dow < 5, 1.0, np.where(dow == 5, 0.28, 0.22))
    t = np.arange(len(days)) / len(days)
    w = w * (1 + 0.18 * t)  # headcount growth
    month = days.month.to_numpy()
    w = w * np.select([month == 12, month == 8, month == 1, month == 9], [0.78, 0.9, 1.08, 1.1],
                      1.0)
    return w


def simulate(n: int = N_TICKETS, seed: int = SEED) -> pd.DataFrame:
    """Return the clean ticket history: one row per ticket, as it stood at the snapshot."""
    rng = np.random.default_rng(seed)
    days = pd.date_range(START, END, freq="D")
    snapshot = pd.Timestamp(SNAPSHOT)

    # Event tickets first, the remaining volume follows the normal weekly/seasonal pattern.
    ev_days, ev_cats = [], []
    for start, end, cat, per_day in EVENTS:
        span = pd.date_range(start, end, freq="D")
        span = span[span.dayofweek < 5]
        k = rng.poisson(per_day, len(span))
        ev_days.append(np.repeat(span.to_numpy(), k))
        ev_cats.append(np.full(k.sum(), cat, dtype=object))
    ev_days = np.concatenate(ev_days)
    ev_cats = np.concatenate(ev_cats)
    n_base = n - len(ev_days)

    w = _daily_weights(days)
    base_days = rng.choice(days.to_numpy(), size=n_base, p=w / w.sum())
    base_cats = rng.choice(np.array([c.name for c in CATEGORIES], dtype=object), size=n_base,
                           p=np.array([c.share for c in CATEGORIES]))
    day = np.concatenate([base_days, ev_days])
    cat = np.concatenate([base_cats, ev_cats])

    # Time of day: office hours on weekdays, flatter at weekends.
    weekday = pd.DatetimeIndex(day).dayofweek.to_numpy() < 5
    hour = np.where(weekday, np.clip(rng.normal(11.5, 2.6, n), 0, 23.99),
                    rng.uniform(0, 24, n))
    opened = pd.DatetimeIndex(day) + pd.to_timedelta(hour * 3600, unit="s").round("s")
    order = np.argsort(opened.to_numpy(), kind="stable")
    opened = opened[order]
    cat = cat[order]

    cats = {c.name: c for c in CATEGORIES}
    prios = {p.name: p for p in PRIORITIES}

    # Priority mix differs by category: security skews urgent, onboarding and printing do not.
    base_p = np.array([p.share for p in PRIORITIES])
    tilt = {"Security": [4.0, 2.2, 0.8, 0.4], "Network & VPN": [1.6, 1.4, 1.0, 0.7],
            "Printing": [0.2, 0.5, 1.0, 1.4], "Onboarding": [0.1, 0.6, 1.1, 1.1]}
    priority = np.empty(n, dtype=object)
    for name in cats:
        mask = cat == name
        p = base_p * np.array(tilt.get(name, [1, 1, 1, 1]))
        priority[mask] = rng.choice(np.array([q.name for q in PRIORITIES], dtype=object),
                                    size=mask.sum(), p=p / p.sum())

    target = np.array([prios[p].resolution_target_hours for p in priority])
    resp_target = np.array([prios[p].response_target_hours for p in priority])
    prio_scale = np.select([priority == "Critical", priority == "High", priority == "Medium"],
                           [0.12, 0.35, 0.85], 1.25)

    # Queue pressure: busier days than the trailing month slow everyone down.
    daily = pd.Series(1, index=opened.normalize()).groupby(level=0).sum()
    daily = daily.reindex(days, fill_value=0)
    pressure = (daily / daily.rolling(28, min_periods=7).mean()).fillna(1.0).clip(0.6, 2.5)
    load = pressure.reindex(opened.normalize()).to_numpy()
    load = 1 + 0.45 * (load - 1)

    work_factor = np.array([cats[c].work_factor for c in cat])
    hop_rate = np.array([cats[c].hop_rate for c in cat])
    wait_prob = np.array([cats[c].wait_prob for c in cat])
    wait_mean = np.array([cats[c].wait_hours for c in cat])

    work = target * work_factor * rng.lognormal(0, 0.62, n) * load
    hops = rng.poisson(hop_rate)
    hop_delay = np.array([rng.exponential(np.minimum(0.16 * t, 5.0) + 0.4, h).sum()
                          for t, h in zip(target, hops, strict=True)])
    waits = rng.random(n) < wait_prob
    wait = np.where(waits, rng.exponential(wait_mean * prio_scale), 0.0)
    reopened = rng.random(n) < 0.035
    reopen_extra = np.where(reopened, rng.exponential(0.4 * target), 0.0)
    # A small share of tickets stall (owner on leave, lost in a queue) and age for weeks.
    stalled = rng.random(n) < 0.035
    stall_extra = np.where(stalled, rng.exponential(380, n), 0.0)
    resolution_h = work + hop_delay + wait + reopen_extra + stall_extra

    response_h = resp_target * rng.lognormal(np.log(0.38), 0.7, n) * load
    response_h = np.minimum(response_h, resolution_h * 0.9)

    first_response = opened + pd.to_timedelta(response_h * 3600, unit="s").round("s")
    resolved = opened + pd.to_timedelta(resolution_h * 3600, unit="s").round("s")
    closed = resolved + pd.Timedelta(days=3)

    is_resolved = resolved <= snapshot
    is_closed = closed <= snapshot
    status = np.where(is_closed, "Closed", np.where(is_resolved, "Resolved", "")).astype(object)
    open_mask = ~is_resolved
    status[open_mask] = np.where(waits[open_mask], "Pending",
                                 np.where(hops[open_mask] > 0, "In Progress", "Open"))
    first_response = pd.Series(first_response).where(first_response <= snapshot)
    resolved_col = pd.Series(resolved).where(is_resolved)
    closed_col = pd.Series(closed).where(is_closed)
    stale_touch = pd.Series(opened + pd.Timedelta(hours=2)).clip(upper=snapshot)
    updated = closed_col.fillna(resolved_col).fillna(stale_touch)

    group = np.array([cats[c].group for c in cat], dtype=object)
    agent = np.array([rng.choice(GROUP_AGENTS[g]) for g in group], dtype=object)
    subcat = np.array([rng.choice(cats[c].subcategories) for c in cat], dtype=object)
    wait_reason = np.where(waits, np.array([cats[c].wait_reason for c in cat], dtype=object), "")

    df = pd.DataFrame({
        "ticket_id": [f"INC{i:07d}" for i in range(1_000_001, 1_000_001 + n)],
        "opened_at": opened.to_numpy(),
        "first_response_at": first_response.to_numpy(),
        "resolved_at": resolved_col.to_numpy(),
        "closed_at": closed_col.to_numpy(),
        "updated_at": updated.to_numpy(),
        "status": status,
        "priority": priority,
        "category": cat,
        "subcategory": subcat,
        "assignment_group": group,
        "assigned_agent": agent,
        "channel": _pick(rng, CHANNELS, n),
        "department": _pick(rng, DEPARTMENTS, n),
        "site": _pick(rng, SITES, n),
        "reassignment_count": hops,
        "reopened": reopened.astype(int),
        "wait_reason": wait_reason,
    })
    return df[COLUMNS]


# ---------------------------------------------------------------------------------------------
# Export defects


@dataclass
class Injected:
    """Answer key: the ticket ids each defect was injected into."""
    exact_duplicates: list[str]
    stale_versions: list[str]
    missing_category: list[str]
    missing_priority: list[str]
    missing_group: list[str]
    missing_opened: list[str]
    category_variants: list[str]
    priority_variants: list[str]
    resolved_before_opened: list[str]
    response_before_opened: list[str]
    closed_before_resolved: list[str]
    opened_after_snapshot: list[str]
    resolved_status_without_time: list[str]
    open_status_with_resolution: list[str]

    def as_dict(self) -> dict[str, list[str]]:
        return dict(self.__dict__)


CATEGORY_VARIANTS = {
    "Access & Identity": ["IAM", "access", "Identity/Access", "ACCESS & IDENTITY ", "Password"],
    "Network & VPN": ["VPN", "network", "Network/VPN", " Network & VPN"],
    "Software": ["Application", "software", "SW"],
    "Hardware": ["Hardware Issue", "HW", "hardware "],
    "Email & Collaboration": ["Email", "Outlook", "Teams"],
    "Printing": ["Printer", "print"],
    "Onboarding": ["New Starter", "onboarding"],
    "Security": ["InfoSec", "security"],
}
PRIORITY_VARIANTS = {"Critical": ["P1", "1 - Critical", "crit"], "High": ["P2", "HIGH", "2 - High"],
                     "Medium": ["P3", "med", "3 - Medium"], "Low": ["P4", "low", "4 - Low"]}


def _fmt(values) -> np.ndarray:
    """Format timestamps the way the export writes them; blanks for missing values."""
    return pd.Series(pd.to_datetime(values)).dt.strftime("%Y-%m-%d %H:%M:%S").fillna("").to_numpy()


def export_raw(clean: pd.DataFrame, seed: int = SEED) -> tuple[pd.DataFrame, Injected]:
    """Turn the clean history into a messy CSV-style export (all text) plus its answer key.

    Each ticket receives at most one defect, so the answer key is unambiguous.
    """
    rng = np.random.default_rng(seed + 1)
    raw = clean.copy()
    for col in ["opened_at", "first_response_at", "resolved_at", "closed_at", "updated_at"]:
        raw[col] = _fmt(raw[col])
    raw = raw.astype({"reassignment_count": str, "reopened": str})

    pool = rng.permutation(len(raw))
    cursor = 0

    def take(k: int, mask: np.ndarray | None = None) -> np.ndarray:
        nonlocal cursor, pool
        if mask is None:
            idx = pool[cursor:cursor + k]
            cursor += k
            return idx
        eligible = pool[cursor:][mask[pool[cursor:]]][:k]
        pool = np.concatenate([pool[:cursor], eligible,
                               np.setdiff1d(pool[cursor:], eligible, assume_unique=True)])
        cursor += len(eligible)
        return eligible

    resolved_mask = (raw["resolved_at"] != "").to_numpy()
    closed_mask = (raw["closed_at"] != "").to_numpy()
    open_mask = ~resolved_mask
    ids = raw["ticket_id"].to_numpy()

    # Label drift
    i = take(1900)
    raw.loc[i, "category"] = [rng.choice(CATEGORY_VARIANTS[c]) for c in raw.loc[i, "category"]]
    cat_var = ids[i]
    i = take(900)
    raw.loc[i, "priority"] = [rng.choice(PRIORITY_VARIANTS[p]) for p in raw.loc[i, "priority"]]
    prio_var = ids[i]

    # Blank fields
    i = take(180)
    raw.loc[i, "category"] = ""
    miss_cat = ids[i]
    i = take(140)
    raw.loc[i, "priority"] = ""
    miss_prio = ids[i]
    i = take(220)
    raw.loc[i, "assignment_group"] = ""
    miss_group = ids[i]
    i = take(25)
    raw.loc[i, "opened_at"] = ""
    miss_open = ids[i]

    # Broken timelines
    i = take(120, resolved_mask)
    op = pd.to_datetime(raw.loc[i, "opened_at"])
    raw.loc[i, "resolved_at"] = _fmt(op - pd.to_timedelta(rng.uniform(1, 48, len(i)), unit="h"))
    res_before = ids[i]
    i = take(60)
    op = pd.to_datetime(raw.loc[i, "opened_at"])
    raw.loc[i, "first_response_at"] = _fmt(op - pd.to_timedelta(rng.uniform(5, 600, len(i)),
                                                                 unit="m"))
    resp_before = ids[i]
    i = take(50, closed_mask)
    rs = pd.to_datetime(raw.loc[i, "resolved_at"])
    raw.loc[i, "closed_at"] = _fmt(rs - pd.to_timedelta(rng.uniform(1, 72, len(i)), unit="h"))
    closed_before = ids[i]
    i = take(15, open_mask)
    raw.loc[i, "opened_at"] = _fmt(pd.Timestamp(SNAPSHOT) + pd.to_timedelta(
        rng.uniform(1, 400, len(i)), unit="D"))
    future = ids[i]
    i = take(70, resolved_mask & ~closed_mask)
    raw.loc[i, "resolved_at"] = ""
    resolved_no_time = ids[i]
    i = take(40, resolved_mask & ~closed_mask)
    raw.loc[i, "status"] = "In Progress"
    open_with_res = ids[i]

    # Stale re-exports: an older copy of the ticket, still Open, with an earlier updated_at.
    i = take(350, resolved_mask)
    stale = raw.loc[i].copy()
    stale["status"] = "In Progress"
    stale[["resolved_at", "closed_at"]] = ""
    stale["updated_at"] = _fmt(pd.to_datetime(stale["opened_at"]) + pd.Timedelta(minutes=45))
    stale_ids = ids[i]

    # Exact duplicates: the same row exported twice.
    i = take(600)
    dupes = raw.loc[i].copy()
    dupe_ids = ids[i]

    out = pd.concat([raw, stale, dupes], ignore_index=True)
    out = out.sample(frac=1, random_state=seed).reset_index(drop=True)

    key = Injected(
        exact_duplicates=list(dupe_ids), stale_versions=list(stale_ids),
        missing_category=list(miss_cat), missing_priority=list(miss_prio),
        missing_group=list(miss_group), missing_opened=list(miss_open),
        category_variants=list(cat_var), priority_variants=list(prio_var),
        resolved_before_opened=list(res_before), response_before_opened=list(resp_before),
        closed_before_resolved=list(closed_before), opened_after_snapshot=list(future),
        resolved_status_without_time=list(resolved_no_time),
        open_status_with_resolution=list(open_with_res),
    )
    return out, key
