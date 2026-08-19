"""
optimizer.py — AquaFair
AGENT 2
Owner: A

Takes: a list of CLAIM dicts (from farm_agent.py) + total water available
Gives back: a list of ALLOCATION rows, one per farm.

────────────────────────────────────────────────────────────────────────
THREE POLICY MODES — the toggle in app.py maps straight onto these.

  "yield_max"   NO survival floor. Pure greedy by Ky x expected yield.
                Highest scorer gets its FULL requirement, then the next,
                until the water runs out. Farms at the bottom get zero
                and their crop dies outright.
                This is the BAD BASELINE we show on stage. It is not a
                strawman — it is what pure efficiency optimisation does.

  "equity"      DEFAULT. Both passes. Every farm gets its survival
                minimum first, then surplus is shared by priority score
                with all fairness weights active.

  "emergency"   Survival floor only, then whatever is left is split in
                proportion to remaining need — no priority scoring at
                all. Use when the WUA wants a defensible, unarguable
                split rather than an optimised one.
────────────────────────────────────────────────────────────────────────

PRIORITY SCORE (equity mode)

    ky * food_weight * shortage_gap * smallholder_boost
       * (1 + fairness_debt) * urgency

  ky                 crop sensitivity right now          [FAO-33]
  food_weight        policy: staples over cash crops     [OUR CHOICE]
  shortage_gap       water_required - survival_minimum
  smallholder_boost  equity lever                        [OUR CHOICE]
  fairness_debt      sum(1 - satisfaction) over recent cycles. This is
                     fair queuing — the same idea internet routers use.
                     A farm short-changed last cycle ranks higher now.
  urgency            escalation from coordinator.py's contest loop

  NOTE we deliberately do NOT multiply by expected_yield_kg, even though
  an early draft of the formula did. Scoring by absolute yield favours
  whoever already produces most: big farms win surplus, small farms lose
  yield, rank lower next cycle, and the gap widens forever. Nobody codes
  discrimination — the formula just rewards the already-large. The
  shortage_gap term already scales with farm size enough.
"""

SMALLHOLDER_BOOST = 1.3   # equity lever — AquaFair's core fairness weight
POLICY_MODES = ("yield_max", "equity", "emergency")


def compute_priority_score(claim, urgency=1.0, use_fairness=True):
    """Higher score = stronger claim on surplus water."""
    gap = max(0, claim["water_required_L"] - claim["survival_minimum_L"])

    boost = 1.0
    debt = 0.0
    if use_fairness:
        if claim.get("is_smallholder"):
            boost = SMALLHOLDER_BOOST
        debt = float(claim.get("fairness_debt", 0.0))

    return claim["ky"] * claim["food_weight"] * gap * boost * (1.0 + debt) * urgency


def _yield_max_score(claim):
    """Greedy efficiency score for the bad-baseline mode. Ky x yield —
    no food weight, no smallholder boost, no fairness debt. Purely
    'protect the most tonnage'."""
    return claim["ky"] * claim["expected_yield_kg"]


def _share_out(pool, shares, open_gaps, allocated):
    """Hand out `pool` litres in proportion to `shares`, capping each
    farm at its remaining gap, and recycling anything freed by a capped
    farm back to the others. Returns the pool left over."""
    while pool > 1e-6 and open_gaps:
        total = sum(shares[f] for f in open_gaps)

        if total <= 0:
            # No priority signal left — split the remainder evenly.
            each = pool / len(open_gaps)
            for f in list(open_gaps):
                give = min(each, open_gaps[f])
                allocated[f] += give
                pool -= give
                open_gaps[f] -= give
                if open_gaps[f] <= 1e-6:
                    del open_gaps[f]
            break

        gave = 0.0
        for f in list(open_gaps):
            give = min(pool * (shares[f] / total), open_gaps[f])
            allocated[f] += give
            gave += give
            open_gaps[f] -= give
            if open_gaps[f] <= 1e-6:
                del open_gaps[f]

        pool -= gave
        if gave <= 1e-6:
            break   # rounding dust — stop rather than spin forever

    return pool


def allocate(claims, total_water_L, urgency=None, mode="equity"):
    """
    claims:        list of CLAIM dicts (see farm_agent.py)
    total_water_L: water available this period, litres
    urgency:       optional {farm_id: multiplier}, default 1.0.
                   Set by coordinator.py when a farm contests.
    mode:          "yield_max" | "equity" | "emergency"

    Returns a list of ALLOCATION rows:
        farm_id, farmer_name, crop, allocated_L, water_required_L,
        survival_minimum_L, pct_of_need_met, met_survival, priority_score
    """
    if mode not in POLICY_MODES:
        raise ValueError(f"Unknown policy mode {mode!r}. Expected one of {POLICY_MODES}.")
    if not claims:
        return []
    if total_water_L < 0:
        raise ValueError(f"total_water_L must be >= 0, got {total_water_L}")

    urgency = urgency or {}
    w = lambda fid: urgency.get(fid, 1.0)

    allocated = {c["farm_id"]: 0.0 for c in claims}
    scores = {}

    # ── yield_max: no survival floor at all ──────────────────────
    if mode == "yield_max":
        for c in claims:
            scores[c["farm_id"]] = _yield_max_score(c)
        pool = float(total_water_L)
        # strict greedy: fill each farm completely, best score first
        for c in sorted(claims, key=lambda c: -scores[c["farm_id"]]):
            if pool <= 0:
                break
            give = min(c["water_required_L"], pool)
            allocated[c["farm_id"]] = give
            pool -= give

    else:
        # ── PASS 1 — survival floor, both equity and emergency ────
        total_survival = sum(c["survival_minimum_L"] for c in claims)

        if total_survival <= total_water_L:
            for c in claims:
                allocated[c["farm_id"]] = float(c["survival_minimum_L"])
            pool = float(total_water_L) - total_survival
        else:
            # Cannot cover every floor. Split proportional to
            # (survival_minimum * urgency) so a farm the coordinator has
            # escalated loses less ground than one it hasn't.
            wt = sum(c["survival_minimum_L"] * w(c["farm_id"]) for c in claims)
            for c in claims:
                share = (c["survival_minimum_L"] * w(c["farm_id"]) / wt) if wt > 0 else 0.0
                allocated[c["farm_id"]] = float(total_water_L) * share
            pool = 0.0

        # ── PASS 2 — share the surplus ───────────────────────────
        if mode == "emergency":
            # Proportional to remaining need. No scoring, no weights —
            # deliberately unarguable rather than optimised.
            for c in claims:
                scores[c["farm_id"]] = max(
                    0, c["water_required_L"] - c["survival_minimum_L"]
                )
        else:  # equity
            for c in claims:
                scores[c["farm_id"]] = compute_priority_score(
                    c, urgency=w(c["farm_id"]), use_fairness=True
                )

        open_gaps = {
            c["farm_id"]: c["water_required_L"] - allocated[c["farm_id"]]
            for c in claims
        }
        open_gaps = {f: g for f, g in open_gaps.items() if g > 1e-6}
        _share_out(pool, scores, open_gaps, allocated)

    # ── round to whole litres WITHOUT breaking the water budget ──
    # Naive round() on each farm can push the total above what exists.
    # Round down, then hand the remainder out one litre at a time to the
    # farms with the largest fractional part.
    floors = {f: int(v) for f, v in allocated.items()}
    spare = int(min(sum(allocated.values()), total_water_L)) - sum(floors.values())
    for f, _ in sorted(allocated.items(), key=lambda kv: -(kv[1] - int(kv[1]))):
        if spare <= 0:
            break
        room = claims_need = None
        for c in claims:
            if c["farm_id"] == f:
                claims_need = c["water_required_L"]
                break
        if floors[f] < claims_need:
            floors[f] += 1
            spare -= 1

    # team rule #2 — never hand out more water than exists
    handed_out = sum(floors.values())
    assert handed_out <= total_water_L, (
        f"Over-allocation: {handed_out:,} L handed out of "
        f"{total_water_L:,} L available (mode={mode})"
    )

    # ── build the ALLOCATION rows ────────────────────────────────
    results = []
    for c in claims:
        fid = c["farm_id"]
        given = floors[fid]
        need = c["water_required_L"]
        results.append({
            "farm_id": fid,
            "farmer_name": c["farmer_name"],
            "crop": c["crop"],
            "allocated_L": given,
            "water_required_L": need,
            "survival_minimum_L": c["survival_minimum_L"],
            "pct_of_need_met": round((given / need) * 100, 1) if need > 0 else 100.0,
            # tolerate 1 L of rounding dust rather than flag a farm unmet
            # when it is a single litre short of its floor
            "met_survival": given >= c["survival_minimum_L"] - 1,
            "priority_score": round(scores.get(fid, 0.0), 2),
        })

    return results


if __name__ == "__main__":
    # manual check — not part of the app.
    # fake_claims is imported HERE, not at module level, so importing
    # optimizer never drags demo data into production code.
    from constants import WEATHER_STATES
    from fake_claims import FAKE_CLAIMS

    water = WEATHER_STATES["drought"]["tank_liters"]
    print(f"DROUGHT — {water:,} L available\n")

    for mode in POLICY_MODES:
        rows = allocate(FAKE_CLAIMS, water, mode=mode)
        total = sum(r["allocated_L"] for r in rows)
        dead = sum(1 for r in rows if not r["met_survival"])
        print(f"--- mode={mode} ---")
        for r in rows:
            flag = "  CROP LOST" if not r["met_survival"] else ""
            print(f"  {r['farm_id']} {r['crop']:<10} "
                  f"{r['allocated_L']:>8,} L / {r['water_required_L']:>8,} L "
                  f"({r['pct_of_need_met']:>5.1f}%){flag}")
        print(f"  allocated {total:,} L of {water:,} L | crops lost: {dead}\n")

    print("--- fairness ledger check (equity mode) ---")
    seeded = [dict(c) for c in FAKE_CLAIMS]
    seeded[2]["fairness_debt"] = 1.2          # F003 ragi was short-changed
    base = {r["farm_id"]: r["allocated_L"] for r in allocate(FAKE_CLAIMS, water)}
    after = {r["farm_id"]: r["allocated_L"] for r in allocate(seeded, water)}
    for fid in base:
        d = after[fid] - base[fid]
        print(f"  {fid}  {base[fid]:>8,} -> {after[fid]:>8,} L  ({d:+,} L)")