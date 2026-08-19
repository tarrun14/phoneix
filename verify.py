"""
verify.py — AquaFair
Run this on your own machine to check the whole project works.

    python3 verify.py

Checks, in order:
  1. every module imports
  2. constants tables are complete and consistent
  3. the source registry is sane
  4. every farm has every field
  5. fake_claims still matches the engine
  6. every source x scenario x policy allocates without error
  7. the invariants that must never break
  8. edge cases: zero water, no demand, one farm, 200 farms

Exit code 0 = safe to demo. 1 = something is wrong, and it says what.
This does NOT check the dashboard renders — for that, run streamlit and
click through Normal / Drought / Rain on each source.
"""

import sys
import traceback

FAILS = []
CHECKS = 0


def check(label, fn):
    global CHECKS
    CHECKS += 1
    try:
        detail = fn()
        print(f"  ok    {label}" + (f"  —  {detail}" if detail else ""))
    except AssertionError as e:
        FAILS.append(f"{label}: {e}")
        print(f"  FAIL  {label}\n          {e}")
    except Exception as e:                       # noqa: BLE001
        FAILS.append(f"{label}: {type(e).__name__}: {e}")
        print(f"  FAIL  {label}\n          {type(e).__name__}: {e}")
        traceback.print_exc(limit=2)


print("\n=== 1. imports ===")

MODULES = ["constants", "sources", "generate", "farm_agent",
           "optimizer", "coordinator", "impact"]
for _m in MODULES:
    check(_m, lambda m=_m: __import__(m) and None)

if FAILS:
    print("\nCannot continue — fix the imports first.")
    sys.exit(1)

import constants as C            # noqa: E402
import sources as S              # noqa: E402
from generate import (demo_farms, generate_farms,          # noqa: E402
                      farms_for_source)
from farm_agent import build_claims                        # noqa: E402
from impact import run_scenario                            # noqa: E402


<<<<<<< Updated upstream
=======
# ═════════════════════════════════════════════════════════════════
print("\n=== 1b. data files ===")
# Two data files now live outside Python: the tank registry and the demo
# farms. They are easy to forget in a commit, and the failure without
# this section surfaces three checks later as something unrelated —
# "CYCLE_DAYS and source volume are compatible" is a confusing first
# thing to read when the real problem is a missing CSV.


def _sources_db():
    import db
    loaded = S.load_sources(refresh=True)
    assert loaded, "the sources table loaded but holds no records"
    return f"{db.DB_PATH.name}: {len(loaded)} source(s)"


check("SQLite registry loads and validates", _sources_db)


def _json_seeds_db():
    """The JSON is the editable source; the database must reflect it.

    Two copies of the same four tanks that could disagree would be
    worse than one — this asserts they cannot."""
    import db
    j = db.read_json()
    d = S.load_sources(refresh=True)
    assert set(j) == set(d), \
        f"sources.json and the database hold different ids: {set(j) ^ set(d)}"
    for sid in j:
        for field in ("live_storage_L", "capacity_L",
                      "conveyance_efficiency", "command_area_ha"):
            assert j[sid][field] == d[sid][field], (
                f"{sid}.{field}: sources.json says {j[sid][field]}, the "
                f"database says {d[sid][field]} — run python db.py --rebuild")
    return f"{db.JSON_PATH.name} and {db.DB_PATH.name} agree on {len(j)} source(s)"


check("JSON source and database agree", _json_seeds_db)


def _db_constraints():
    """The CHECK constraints must actually be enforced.

    A schema whose constraints were dropped in a rebuild would accept a
    gauge reading above full supply level, and nothing downstream would
    notice until an allocation looked wrong. Cheap to verify, rolled
    back immediately."""
    import sqlite3, db
    con = db.connect()
    try:
        for sql, tag in [
            ("UPDATE sources SET live_storage_L = 99000000 WHERE id='T01'",
             "storage above capacity"),
            ("UPDATE sources SET conveyance_efficiency = 1.5 WHERE id='T01'",
             "efficiency above 1.0"),
            ("INSERT INTO sources VALUES ('X01','B','river',1,1,0.5,1,'W')",
             "type outside tank/canal"),
        ]:
            try:
                con.execute(sql)
                raise AssertionError(f"database accepted {tag}")
            except sqlite3.IntegrityError:
                pass
    finally:
        con.rollback()
        con.close()
    return "bad writes refused by the schema, not by Python"


check("database constraints are enforced", _db_constraints)


def _farms_file():
    from generate import DEMO_FARMS_CSV, load_demo_spec
    spec = load_demo_spec()
    assert spec, "demo_farms.csv loaded but holds no rows"
    known = {s for s in S.list_sources()}
    orphans = sorted({r["source_id"] for r in spec} - known)
    assert not orphans, (
        f"{DEMO_FARMS_CSV.name} references source(s) not in the "
        f"database: {orphans}")
    return f"{DEMO_FARMS_CSV.name}: {len(spec)} farm(s)"


check("demo_farms.csv loads and validates", _farms_file)


# ═════════════════════════════════════════════════════════════════
>>>>>>> Stashed changes
print("\n=== 2. constants ===")


def _tables_aligned():
    tables = {"KC": C.KC, "KY": C.KY, "SURVIVAL_MIN": C.SURVIVAL_MIN,
              "FOOD_WEIGHT": C.FOOD_WEIGHT,
              "TYPICAL_YIELD_KG_PER_M2": C.TYPICAL_YIELD_KG_PER_M2,
              "MARKET_PRICE_PER_KG": C.MARKET_PRICE_PER_KG}
    for name, t in tables.items():
        assert set(t) == set(C.CROPS), \
            f"{name} crops differ from KC: {set(t) ^ set(C.CROPS)}"
    return f"{len(C.CROPS)} crops across 6 tables"


check("all crop tables cover the same crops", _tables_aligned)


def _stage_keys():
    for crop in C.CROPS:
        assert set(C.KC[crop]) == set(C.STAGES), f"KC[{crop}]"
        assert set(C.KY[crop]) == set(C.KY_STAGES), f"KY[{crop}]"
    return None


check("every crop has all four stages in KC and KY", _stage_keys)


def _demo_line():
    m = C.KY["maize"]
    ratio = m["flowering"] / m["ripening"]
    assert abs(ratio - 7.5) < 0.01, f"maize ratio is {ratio:.2f}, expected 7.5"
    return "maize flowering 1.50 vs ripening 0.20 = 7.5x"


check("the maize demo line still holds", _demo_line)


def _cycle_coupling():
    farms = demo_farms("T01")
    claims = build_claims(farms, C.WEATHER_STATES["drought"])
    survival = sum(c["survival_minimum_L"] for c in claims)
    tank = S.deliverable_water_L("T01")
    assert survival <= tank, (
        f"T01 survival floor {survival:,.0f} L exceeds deliverable "
        f"{tank:,.0f} L — Pass 1 is infeasible and the contest loop "
        f"cannot converge")
    return f"survival {survival:,.0f} L fits in {tank:,.0f} L deliverable"


check("CYCLE_DAYS and tank size are compatible", _cycle_coupling)


print("\n=== 3. sources ===")


def _registry():
    for sid in S.list_sources():
        r = S.get_source(sid)
        assert r["live_storage_L"] <= r["capacity_L"], f"{sid} over capacity"
        assert 0 < r["conveyance_efficiency"] <= 1, f"{sid} efficiency"
        assert r["command_area_ha"] > 0, f"{sid} command area"
    tanks = sum(1 for s in S.list_sources() if S.get_source(s)["type"] == "tank")
    return f"{len(S.list_sources())} sources ({tanks} tanks, " \
           f"{len(S.list_sources()) - tanks} canals)"


check("registry values are sane", _registry)


def _conveyance():
    lines = []
    for sid in S.list_sources():
        r = S.get_source(sid)
        lost = S.conveyance_loss_L(sid)
        assert lost > 0, f"{sid} loses nothing in transit — efficiency is 1.0?"
        lines.append(f"{sid} loses {lost:,.0f} L")
    return "; ".join(lines)


check("conveyance loss is modelled", _conveyance)


print("\n=== 4. farms ===")

FARM_FIELDS = ["farm_id", "source_id", "farmer_name", "crop", "stage",
               "area_m2", "expected_yield_kg", "is_smallholder",
               "fairness_debt", "distance_from_head_m"]


def _farm_fields():
    for f in demo_farms():
        missing = [k for k in FARM_FIELDS if k not in f or f[k] is None]
        assert not missing, f"{f.get('farm_id')} missing {missing}"
        assert f["crop"] in C.CROPS, f"{f['farm_id']} unknown crop {f['crop']}"
        assert f["stage"] in C.STAGES, f"{f['farm_id']} bad stage"
        assert f["area_m2"] > 0, f"{f['farm_id']} zero area"
    return f"{len(demo_farms())} demo farms, all fields present"


check("every demo farm is complete", _farm_fields)


def _farms_per_source():
    parts = []
    for sid in S.list_sources():
        n = len(demo_farms(sid))
        assert n > 0, f"{sid} has no farms — the dashboard will show an " \
                      f"empty command area"
        parts.append(f"{sid}:{n}")
    return " ".join(parts)


check("every source has farms", _farms_per_source)


def _isolation():
    all_farms = demo_farms()
    for sid in S.list_sources():
        served = farms_for_source(all_farms, sid)
        assert all(f["source_id"] == sid for f in served), \
            f"{sid} filter leaked a farm from another source"
    total = sum(len(farms_for_source(all_farms, s)) for s in S.list_sources())
    assert total == len(all_farms), \
        f"{len(all_farms) - total} farm(s) belong to no known source"
    return "no farm appears under two sources"


check("command areas are isolated", _isolation)


def _debt_seeded():
    n = sum(1 for f in demo_farms() if f["fairness_debt"] > 0)
    assert n > 0, "no farm carries a fairness debt — the ledger will " \
                  "render blank on every card"
    return f"{n} farms carry a debt"


check("fairness ledger has something to show", _debt_seeded)


print("\n=== 5. fake_claims drift ===")


def _drift():
    try:
        from fake_claims import FAKE_CLAIMS
    except ImportError:
        return "fake_claims.py not present (fine — nothing needs it)"
    live = {c["farm_id"]: c
            for c in build_claims(demo_farms(), C.WEATHER_STATES["normal"])}
    stored = {c["farm_id"]: c for c in FAKE_CLAIMS}
    assert set(live) == set(stored), \
        f"farm sets differ: only live {sorted(set(live)-set(stored))}, " \
        f"only stored {sorted(set(stored)-set(live))}"
    drift = [f for f in live if live[f] != stored[f]]
    assert not drift, f"values drifted for {drift} — run python3 fake_claims.py"
    return f"{len(stored)} claims match the engine"


check("fake_claims matches the engine", _drift)


print("\n=== 6 & 7. allocation and invariants ===")

SCENARIOS = ["normal", "drought", "rain"]
MODES = ["equity", "yield_max", "emergency"]


def _run(sid, scen, mode, farms=None):
    fs = farms if farms is not None else demo_farms(sid)
    w = dict(C.WEATHER_STATES[scen])
    w["tank_liters"] = S.deliverable_water_L(sid)
    return run_scenario(fs, w, mode=mode, scale_tank=False)


def _invariants(out, tag):
    claims = {c["farm_id"]: c for c in out["claims"]}
    alloc = out["allocation"]
    tank = out["tank_L"]

    handed = sum(a["total_L"] for a in alloc.values())
    assert handed <= tank + 1, \
        f"{tag}: allocated {handed:,.0f} L of {tank:,.0f} L available"
    assert set(claims) == set(alloc), \
        f"{tag}: {sorted(set(claims) ^ set(alloc))} has no allocation row"

    for fid, a in alloc.items():
        c = claims[fid]
        assert a["total_L"] <= c["water_required_L"] + 1, \
            f"{tag}: {fid} got more than it asked for"
        assert 0.0 <= a["satisfaction"] <= 1.0, \
            f"{tag}: {fid} satisfaction {a['satisfaction']}"
        assert abs(a["survival_L"] + a["surplus_L"] - a["total_L"]) <= 1, \
            f"{tag}: {fid} survival + surplus != total"


for _sid in S.list_sources():
    for _scen in SCENARIOS:
        def _combo(sid=_sid, scen=_scen):
            for mode in MODES:
                out = _run(sid, scen, mode)
                _invariants(out, f"{sid}/{scen}/{mode}")
            eq = _run(sid, scen, "equity")
            if not eq["coordination"]["supply_infeasible"]:
                lost = eq["scorecard"]["equity"]["crops_lost"]
                assert lost == 0, (
                    f"{sid}/{scen}: equity mode lost {lost} crop(s) with "
                    f"feasible supply — the survival floor is not holding")
            d = sum(c["water_required_L"] for c in eq["claims"])
            gap = (1 - eq["tank_L"] / d) * 100 if d else 0
            return f"{gap:+.0f}% gap, {eq['coordination']['rounds_used']} round(s)"

        check(f"{_sid} / {_scen} (all 3 policies)", _combo)


<<<<<<< Updated upstream
def _money_slide():
    h = _run("T01", "drought", "equity")["scorecard"]["headline"]
    assert h["aquafair_crops_lost"] < h["yieldmax_crops_lost"], (
        f"AquaFair lost {h['aquafair_crops_lost']}, yield_max lost "
        f"{h['yieldmax_crops_lost']} — no contrast to demo")
    return (f"yield_max loses {h['yieldmax_crops_lost']}, "
            f"AquaFair loses {h['aquafair_crops_lost']}")


check("T01 drought money slide points the right way", _money_slide)
=======
def _every_source_populated():
    """Load 100 must never leave a command area empty.

    T01 is 3% of the district by area, so a purely weighted draw can
    legitimately give it zero farms — and the dashboard then shows "no
    farms registered" and nothing else. On stage that looks exactly
    like a broken Load 100 button."""
    for seed in (42, 1, 7, 99):
        farms = generate_farms(100, seed=seed)
        empty = [s for s in S.list_sources()
                 if not farms_for_source(farms, s)]
        assert not empty, \
            f"generate_farms(100, seed={seed}) left {empty} with no farms"
    return "every source populated across 4 seeds"


check("Load 100 populates every command area", _every_source_populated)


def _head_to_tail_is_ordered():
    """Current practice must actually serve head to tail.

    Without a position on every claim the sort falls back to farm_id,
    and the baseline stops being about the channel — it becomes an
    arbitrary order dressed up as one. This asserts the water really
    does run out down the line."""
    from impact import head_to_tail_split
    for sid in S.list_sources():
        claims = build_claims(demo_farms(sid), C.WEATHER_STATES["drought"])
        assert all(c.get("distance_from_head_m") is not None
                   for c in claims), f"{sid}: a claim has no position"
        given = head_to_tail_split(claims, S.deliverable_water_L(sid))
        ordered = sorted(claims, key=lambda c: c["distance_from_head_m"])
        seen_partial = False
        for c in ordered:
            got, need = given[c["farm_id"]], c["water_required_L"]
            if seen_partial:
                assert got == 0, (
                    f"{sid}: {c['farm_id']} received {got:,} L after the "
                    f"channel had already run dry upstream")
            elif got < need:
                seen_partial = True
    return "water runs out down the channel, never past a dry farm"


check("head-to-tail serves in channel order", _head_to_tail_is_ordered)


def _new_scorecard_fields():
    """Every field the Impact panel reads, on every policy column."""
    need = ["total_yield_kg", "staple_yield_kg", "crops_lost",
            "farms_below_survival", "farms_with_nothing",
            "smallholder_kept_pct", "largest_farm_kept_pct",
            "largest_farm_id", "water_used_L", "value_rupees",
            "compensation_rupees", "lost_farm_ids", "potential_yield_kg",
            "staple_potential_kg", "has_smallholders"]
    sc = _run("T01", "drought", "equity")["scorecard"]
    assert "current" in sc, \
        "scorecard has no 'current' column — the Impact panel compares " \
        "against head-to-tail and would KeyError"
    for col in ("current", "yield_max", "naive", "emergency", "equity"):
        missing = [f for f in need if f not in sc[col]]
        assert not missing, f"scorecard['{col}'] is missing {missing}"
    return f"{len(need)} fields on 5 policy columns"


check("Impact panel has every field it reads", _new_scorecard_fields)


def _compensation_costed():
    """Crops lost must cost money, and zero lost must cost nothing."""
    sc = _run("T01", "drought", "equity")["scorecard"]
    for col in ("current", "yield_max", "equity"):
        row = sc[col]
        if row["crops_lost"] == 0:
            assert row["compensation_rupees"] == 0, \
                f"{col}: no crops lost but compensation is " \
                f"{row['compensation_rupees']:,}"
        else:
            assert row["compensation_rupees"] > 0, \
                f"{col}: {row['crops_lost']} crop(s) lost but no " \
                f"compensation costed"
    return (f"AquaFair owes ₹{sc['equity']['compensation_rupees']:,}, "
            f"current practice ₹{sc['current']['compensation_rupees']:,}")


check("compensation tracks crops lost", _compensation_costed)
>>>>>>> Stashed changes


def _crops_lost_everywhere():
    for sid in S.list_sources():
        h = _run(sid, "drought", "equity")["scorecard"]["headline"]
        assert h["aquafair_crops_lost"] == 0, \
            f"{sid}: AquaFair lost {h['aquafair_crops_lost']} crop(s)"
        assert h["yieldmax_crops_lost"] > 0, \
            f"{sid}: yield_max lost nothing — no contrast"
    return "AquaFair loses 0 crops on every source; yield_max does not"


check("the claim that holds on all four sources", _crops_lost_everywhere)


print("\n=== 8. edge cases ===")


def _zero_water():
    out = run_scenario(demo_farms("T01"),
                       {"ETo": 6.2, "rainfall_mm": 0, "tank_liters": 0},
                       scale_tank=False)
    assert sum(a["total_L"] for a in out["allocation"].values()) == 0
    return "empty tank allocates nothing, does not crash"


check("zero water", _zero_water)


def _zero_demand():
    out = run_scenario(demo_farms("T01"),
                       {"ETo": 0.0, "rainfall_mm": 50,
                        "tank_liters": 500_000}, scale_tank=False)
    for a in out["allocation"].values():
        assert a["satisfaction"] == 1.0, "zero requirement should be satisfied"
    return "no demand — no divide-by-zero"


check("zero demand", _zero_demand)


def _one_farm():
    run_scenario(demo_farms("T01")[:1],
                 dict(C.WEATHER_STATES["drought"]), scale_tank=False)
    return None


check("single farm", _one_farm)


def _no_farms():
    out = run_scenario([], dict(C.WEATHER_STATES["normal"]), scale_tank=False)
    assert out["allocation"] == {}
    return "empty list returns empty allocation"


check("no farms", _no_farms)


def _big():
    farms = generate_farms(200, seed=1)
    n = 0
    for sid in S.list_sources():
        fs = farms_for_source(farms, sid)
        if not fs:
            continue
        w = dict(C.WEATHER_STATES["drought"])
        w["tank_liters"] = S.deliverable_water_L(sid)
        out = run_scenario(fs, w, scale_tank=False)
        _invariants(out, f"{sid}/200farms")
        n += len(out["allocation"])
    assert n == len(farms), f"{len(farms) - n} farms lost across sources"
    return f"200 farms allocated across {len(S.list_sources())} sources"


check("200 farms", _big)


print("\n" + "=" * 70)
if FAILS:
    print(f"  {len(FAILS)} FAILURE(S) out of {CHECKS} checks")
    print("=" * 70)
    for f in FAILS:
        print(f"  x {f}")
    print()
    sys.exit(1)

print(f"  ALL {CHECKS} CHECKS PASSED")
print("=" * 70)
print("  Engine is sound. Still click through the dashboard before you")
print("  demo — this does not render the UI.")
print()
sys.exit(0)