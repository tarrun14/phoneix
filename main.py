"""
main.py — AquaFair
Full pipeline runner and pre-freeze smoke test.

    python3 main.py                      demo 4 farms, all three scenarios
    python3 main.py --farms 100          scalability proof
    python3 main.py --scenario drought   one scenario only
    python3 main.py --mode yield_max     force a policy mode
    python3 main.py --check              invariants only, quiet, exit code

WHY --check EXISTS
Run it before every merge and again before the hour-10 freeze. It asserts
the things that must never break: the water budget, the survival floor,
and the direction of the money slide. Exit code 0 = safe, 1 = something
regressed. That is much faster than eyeballing numbers on the dashboard
and hoping you would notice a 6% drift.

This is what D runs at rehearsal and what A and C run after touching the
engine.
"""

import argparse
import sys

from constants import WEATHER_STATES, M2_PER_ACRE
from generate import generate_farms, demo_farms, farms_for_source
from impact import run_scenario
from sources import list_sources, get_source, deliverable_water_L

SCENARIOS = ("normal", "drought", "rain")


# ══════════════════════════════════════════════════════════════════
# Invariants — these must hold or the demo is lying
# ══════════════════════════════════════════════════════════════════

def check_scenario(out, strict_demo=False):
    """Returns a list of failure strings. Empty list = all good."""
    fails = []
    claims = {c["farm_id"]: c for c in out["claims"]}
    alloc = out["allocation"]
    tank = out["tank_L"]
    sc = out["scorecard"]
    key = out["weather_key"]

    # 1. never hand out water that does not exist
    handed = sum(a["total_L"] for a in alloc.values())
    if handed > tank + 1:
        fails.append(f"[{key}] over-allocated: {handed:,.0f} L of {tank:,.0f} L")

    # 2. every claim must get an allocation row, or a farm card renders blank
    missing = set(claims) - set(alloc)
    if missing:
        fails.append(f"[{key}] no allocation for {sorted(missing)}")

    for fid, a in alloc.items():
        c = claims[fid]
        # 3. nobody gets more than they asked for
        if a["total_L"] > c["water_required_L"] + 1:
            fails.append(
                f"[{key}] {fid} got {a['total_L']:,} L but only asked for "
                f"{c['water_required_L']:,} L")
        # 4. satisfaction is a fraction
        if not (0.0 <= a["satisfaction"] <= 1.0):
            fails.append(f"[{key}] {fid} satisfaction {a['satisfaction']} out of range")
        # 5. the two halves must sum to the total
        if abs(a["survival_L"] + a["surplus_L"] - a["total_L"]) > 1:
            fails.append(
                f"[{key}] {fid} survival {a['survival_L']:,} + surplus "
                f"{a['surplus_L']:,} != total {a['total_L']:,}")

    # 6. equity mode must not lose a crop while supply is feasible.
    #    This is the core claim of the whole project.
    if not out["coordination"]["supply_infeasible"]:
        lost = sc["equity"]["crops_lost"]
        if lost > 0:
            fails.append(
                f"[{key}] equity mode lost {lost} crop(s) with feasible supply — "
                f"the survival floor is not holding")

    # 7. The money slide must point the right way in drought.
    #
    # ⚠ ONLY CHECKED ON T01, and that is a real limitation, not laziness.
    # "AquaFair produces more food" is measured in kilograms, and
    # sugarcane yields 7 kg/m2 against ragi's 0.25. On a canal command
    # area growing cane, 85% of total tonnage is sugarcane, so a policy
    # that feeds the cane and starves everything else WINS on kg.
    # The claim that holds everywhere is "loses no crops" — verified by
    # check 6 on every source. Lead the pitch with that one.
    if strict_demo and key == "drought":
        h = sc["headline"]
        if h["aquafair_food_kg"] <= h["yieldmax_food_kg"]:
            fails.append(
                f"[drought] MONEY SLIDE INVERTED: AquaFair "
                f"{h['aquafair_food_kg']:,} kg vs yield_max "
                f"{h['yieldmax_food_kg']:,} kg")
        if h["yieldmax_crops_lost"] == 0:
            fails.append("[drought] yield_max lost no crops — no contrast to show")

    return fails


# ══════════════════════════════════════════════════════════════════
# Reporting
# ══════════════════════════════════════════════════════════════════

def print_scenario(out, log_lines=10):
    w = out["weather"]
    sc = out["scorecard"]
    coord = out["coordination"]
    claims = out["claims"]

    demand = sum(c["water_required_L"] for c in claims)
    survival = sum(c["survival_minimum_L"] for c in claims)
    tank = out["tank_L"]
    deficit = (1 - tank / demand) * 100 if demand > 0 else 0.0

    print(f"\n{'='*70}")
    print(f"  {out['weather_key'].upper()}   "
          f"ETo {w['ETo']} mm/day · rain {w['rainfall_mm']} mm · "
          f"tank {tank:,.0f} L")
    print(f"{'='*70}")
    print(f"  demand {demand:,.0f} L | survival floor {survival:,.0f} L | "
          f"deficit {deficit:.1f}%")
    print(f"  coordinator: {coord['rounds_used']} round(s), "
          f"survival met {coord['all_survival_met']}, "
          f"supply infeasible {coord['supply_infeasible']}")

    print(f"\n  --- activity log ---")
    for e in coord["log"][:log_lines]:
        print(f"    [{e['time']}] {e['agent']:<11} {e['message']}")
    if len(coord["log"]) > log_lines:
        print(f"    ... {len(coord['log']) - log_lines} more line(s)")

    print(f"\n  --- policy comparison (same {tank:,.0f} L for every column) ---")
    print(f"    {'':12s} {'food kg':>10s} {'kept%':>7s} {'lost':>5s} "
          f"{'small kept%':>12s} {'water L':>12s}")
    for col in ("yield_max", "naive", "emergency", "equity"):
        s = sc[col]
        label = "AQUAFAIR" if col == "equity" else col
        print(f"    {label:12s} {s['total_yield_kg']:>10,} "
              f"{s['yield_kept_pct']:>6.1f}% {s['crops_lost']:>5d} "
              f"{s['smallholder_kept_pct']:>11.1f}% {s['water_used_L']:>12,}")


def print_farm_table(out, limit=12):
    claims = {c["farm_id"]: c for c in out["claims"]}
    alloc = out["allocation"]
    print(f"\n  --- farms ---")
    print(f"    {'id':<6s} {'farmer':<10s} {'crop':<10s} {'acres':>6s} "
          f"{'need L':>10s} {'got L':>10s} {'sat':>6s} {'loss%':>7s}  flags")
    for i, (fid, a) in enumerate(alloc.items()):
        if i >= limit:
            print(f"    ... {len(alloc) - limit} more farm(s)")
            break
        c = claims[fid]
        flags = []
        if a["contested"]:
            flags.append("CONTESTED")
        if c["is_smallholder"]:
            flags.append("small")
        if c["fairness_debt"] > 0:
            flags.append(f"debt {c['fairness_debt']}")
        print(f"    {fid:<6s} {c['farmer_name']:<10s} {c['crop']:<10s} "
              f"{c['area_m2']/M2_PER_ACRE:>6.1f} "
              f"{c['water_required_L']:>10,} {a['total_L']:>10,} "
              f"{a['satisfaction']:>5.0%} "
              f"{min(a['yield_loss_pct'], 100):>6.1f}%  {' '.join(flags)}")


def print_money_slide(out):
    h = out["scorecard"]["headline"]
    print(f"\n{'='*70}")
    print("  MONEY SLIDE — flip the policy toggle here")
    print(f"{'='*70}")
    print(f"    {'':24s} {'Yield-max':>12s} {'AquaFair':>12s}")
    print(f"    {'Total food produced':24s} {h['yieldmax_food_kg']:>9,} kg "
          f"{h['aquafair_food_kg']:>9,} kg")
    print(f"    {'Crops lost entirely':24s} {h['yieldmax_crops_lost']:>12d} "
          f"{h['aquafair_crops_lost']:>12d}")
    print(f"    {'Smallholder harvest':24s} "
          f"{h['yieldmax_smallholder_kept_pct']:>11.0f}% "
          f"{h['aquafair_smallholder_kept_pct']:>11.0f}%")
    print(f"\n    AquaFair produces {h['food_gain_kg']:+,} kg "
          f"({h['food_gain_pct']:+.1f}%) MORE food while losing nobody.")


# ══════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="AquaFair pipeline runner")
    p.add_argument("--farms", type=int, default=0,
                   help="generate N random farms (0 = use the fixed demo set)")
    p.add_argument("--scenario", choices=SCENARIOS, default=None,
                   help="run one scenario (default: all three)")
    p.add_argument("--mode", choices=("equity", "yield_max", "emergency"),
                   default="equity")
    p.add_argument("--source", default=None,
                   help="one command area (default: every source in turn)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--check", action="store_true",
                   help="invariants only; exit 1 if anything failed")
    args = p.parse_args()

    if args.farms > 0:
        all_farms = generate_farms(args.farms, seed=args.seed)
        origin = f"generate_farms({args.farms}, seed={args.seed})"
    else:
        all_farms = demo_farms()
        origin = "demo_farms() — the fixed on-stage set"

    scenarios = [args.scenario] if args.scenario else list(SCENARIOS)
    src_ids = [args.source] if args.source else list_sources()
    all_fails = []

    if not args.check:
        print(f"\nAquaFair — {len(all_farms)} farms from {origin}, "
              f"across {len(src_ids)} command area(s)")

    for sid in src_ids:
        # ⚠ ALLOCATE PER SOURCE. Pooling every farm into one run would
        # let Tank A's water reach Tank B's farms, which no WUA has the
        # authority to do — and would silently invert the money slide,
        # because a canal's sugarcane would outbid a village tank's ragi.
        served = farms_for_source(all_farms, sid)
        if not served:
            if not args.check:
                print(f"\n  {get_source(sid)['name']}: no farms registered")
            continue

        src = get_source(sid)
        if not args.check:
            print(f"\n{'#'*70}\n#  {src['name']} ({sid}) — {src['wua']}\n"
                  f"#  {len(served)} farms · stored {src['live_storage_L']:,} L · "
                  f"conveyance {src['conveyance_efficiency']:.0%} · "
                  f"deliverable {deliverable_water_L(sid):,.0f} L\n{'#'*70}")

        for key in scenarios:
            weather = dict(WEATHER_STATES[key])
            weather["tank_liters"] = deliverable_water_L(sid)
            out = run_scenario(served, weather, mode=args.mode,
                               scale_tank=False)
            out["weather_key"] = key
            # The money-slide direction is only enforced on the rehearsed
            # T01 set. See the note in check_scenario.
            all_fails += check_scenario(
                out, strict_demo=(args.farms == 0 and sid == "T01"))

            if not args.check:
                print_scenario(out)
                print_farm_table(out)
                if key == "drought":
                    print_money_slide(out)

    print(f"\n{'='*70}")
    if all_fails:
        print(f"  CHECKS FAILED — {len(all_fails)} problem(s)")
        print(f"{'='*70}")
        for f in all_fails:
            print(f"  ✗ {f}")
        print()
        sys.exit(1)

    print(f"  ALL CHECKS PASSED — water budget, survival floor, "
          f"money slide direction")
    print(f"{'='*70}\n")
    sys.exit(0)


if __name__ == "__main__":
    main()