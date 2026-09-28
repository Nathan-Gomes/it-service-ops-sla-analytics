# Methodology

How the tickets are simulated, how the quality gate decides what to trust, how SLA outcomes are
defined, and what the analysis can and cannot claim.

## 1. The simulated desk

`serviceops.simulate` generates **50,000 tickets opened between 1 January 2024 and 30 June 2026**
for a mid-sized organisation (five sites, eight departments, six resolver groups, 21 agents).
Everything is seeded (`SEED = 20260630`), so every run produces the same history.

| Component | How it is generated |
|---|---|
| Arrival | Weekday-heavy daily weights (Saturday 0.28, Sunday 0.22 of a weekday), 18% headcount growth across the period, seasonal dips in August and December, office-hours time of day on weekdays |
| Incidents | Four dated events add volume on top: autumn hiring (Sep 2024), a VPN concentrator failure (Feb 2025), the Windows 11 migration (Sep to Oct 2025) and an MFA policy roll-out (Mar 2026) |
| Priority | Base mix of 3% Critical, 14% High, 48% Medium and 35% Low, tilted by category (Security skews urgent; Printing and Onboarding do not) |
| Hands-on work | Log-normal around a category-specific fraction of the priority's target, scaled up on days busier than the trailing 28-day average |
| Hand-offs | Poisson reassignments at a category rate (0.10 for Printing up to 0.90 for Network & VPN), each adding a queue delay |
| Third-party waits | A category-specific chance of waiting on an approver, a carrier, a vendor, parts or HR, with an exponential wait whose length shrinks for urgent tickets |
| Reopens and stalls | 3.5% of tickets are reopened; 3.5% stall (an owner on leave, a lost ticket) and age for weeks |

Nothing in the generator says "breach". Breaches emerge from those mechanisms, which is what lets
the analysis find a *cause* rather than just a count: Access & Identity and Network & VPN are the
two categories with high hand-off rates and frequent third-party waits.

### The export and its defects

Real ITSM exports are messy, so `export_raw` turns the clean history into a CSV-style, all-text
export and injects fourteen defect classes, each into a known set of tickets (no ticket gets two):

| Defect | Rows |
|---|---:|
| Exact duplicate rows | 600 |
| Stale re-exports of a ticket (older copy, still "In Progress") | 350 |
| Non-standard category labels (`IAM`, `VPN`, `Hardware Issue`, stray whitespace) | 1,900 |
| Non-standard priority labels (`P1`, `3 - Medium`, `crit`) | 900 |
| Blank category / priority / assignment group / opened time | 180 / 140 / 220 / 25 |
| Resolved before opened; responded before opened; closed before resolved | 120 / 60 / 50 |
| Opened after the export snapshot | 15 |
| Status "Resolved" with no resolved time; active status with a resolved time | 70 / 40 |

That produces 50,950 exported rows. The answer key is kept, which is what lets the tests assert
that each check finds *exactly* the injected rows, no more and no fewer.

## 2. The quality gate

`serviceops.quality.run_quality_gate` runs fifteen checks in a fixed order. Each check either
removes, repairs or quarantines; nothing is silently dropped.

| Order | Dimension | Rule | Action |
|---|---|---|---|
| U1–U2 | Uniqueness | Exact duplicates; the same ticket id twice (keep the latest `updated_at`) | removed |
| C1–C2 | Consistency | Map legacy and free-text category and priority labels to the taxonomy | repaired |
| M1 | Completeness | Blank category inferred from the subcategory (each belongs to exactly one category) | repaired |
| M2 | Completeness | Blank assignment group restored from the category's routing rule | repaired |
| M3–M4 | Completeness | Blank priority (no SLA target) or blank opened time (no clock start) | quarantined |
| C3 | Consistency | Any label still outside the taxonomy after repair | quarantined |
| V1–V6 | Validity | Opened after the snapshot; resolved/responded before opened; closed before resolved; status and resolved time disagree | quarantined |

Repairs are recorded on the ticket (`dq_repaired`), so any number can be traced back to the rows
that were fixed. The quarantine keeps the raw record and the reason, which is the list a service
desk would hand back to the owning team.

**Result:** 50,950 rows in → 950 removed, 3,200 repaired, 520 quarantined → **49,480 clean
tickets** reported on. The tests also check that the gate is idempotent: run on its own output,
it finds nothing.

## 3. SLA definitions

Targets are calendar hours on a 24x7 desk:

| Priority | First response | Resolution |
|---|---:|---:|
| P1 Critical | 15 min | 4 h |
| P2 High | 1 h | 8 h |
| P3 Medium | 4 h | 24 h |
| P4 Low | 8 h | 72 h |

- **Elapsed time** runs from opened to resolved, or to the snapshot (30 June 2026 23:59:59) if
  the ticket is still open.
- **Breached**: elapsed time exceeds the target. This includes open tickets already past target,
  because their breach is certain.
- **Scored**: resolved tickets plus open tickets already breached. Open tickets still inside
  target are excluded, because their outcome is not known yet.
- **SLA compliance** = (scored − breached) / scored. The service-level objective is 90%.
- **First-response compliance** follows the same rules on the response clock.
- **Backlog** on a day = tickets opened on or before that day and not resolved by its end,
  computed as a running sum of daily opened minus resolved.

These rules live in one place, `vw_ticket_sla` in `sql/views.sql`. The dashboard's filtered
queries (`queries.py`) and the DAX measures (`powerbi/measures.dax`) reproduce the same
expressions, and the tests hold the view, the filtered query and an independent pandas
recomputation to the same numbers.

## 4. The analysis

1. **Pareto.** Rank categories by breach count and accumulate their share (`vw_category_pareto`).
   Access & Identity (32.1%) and Network & VPN (29.1%) together hold **61.2% of breaches** while
   carrying 33.9% of tickets. Their combined breach rate is 23.7%, against 7.7% for the other six
   categories.
2. **Mechanism.** Split the two categories by third-party wait and by hand-off count
   (`vw_breach_drivers`):
   - Access & Identity tickets that waited on manager approval breached 49.7% of the time,
     against 13.6% for those that did not; 52.8% of its breaches involved that wait.
   - Network & VPN tickets handed off two or more times breached 39.0% of the time, against
     19.5% for tickets the first group kept; carrier or vendor waits raised it to 60.3%.
3. **Counterfactual.** If the two categories breached at the rest of the desk's rate, about
   2,682 fewer tickets would have breached and compliance would rise from 86.9% to 92.3%,
   above the 90% objective. This is an upper bound on what fixing the two queues could achieve,
   not a forecast.
4. **Recommendations.** Each one targets a measured mechanism, names an owner and is generated
   from the numbers (`analysis.py`), so the text changes when the data does:
   - pre-approved role-based access bundles, plus approver reminders at 50% of target and
     escalation at 75%;
   - routing rules that send connectivity tickets straight to Network Operations, and a
     response-time clause in the carrier contract;
   - an at-risk alert at 75% of target for both queues, reviewed weekly until their breach rate is
     within two points of the desk average.

## 5. Limits

- **The data is simulated.** The 61% is a property of a generator built to resemble a real desk,
  and the causal story is true *by construction*. The value of the project is the pipeline, the
  quality gate, the SQL layer and the method of going from a Pareto to a mechanism to an action.
  All of that would carry over to a real ITSM export.
- **Calendar hours.** Real contracts often pause the clock outside business hours or while a
  ticket is "Pending customer". Both would change the numbers and are listed as next steps.
- **The counterfactual is associational.** It assumes the two categories could behave like the
  rest of the desk, which a real rollout would need to test, for example by piloting approval
  bundles on one site first.
