"""
generate.py — AquaFair
Owner: C

Takes: n (int)
Gives back: a list of n farm dicts.

Key rule: n is a parameter. generate_farms(4) and generate_farms(100)
both work — that is our scalability proof.

This file is NOT an agent. It fabricates realistic fake inputs because
we have no access to real district records. The maths that consumes this
output (farm_agent.py, optimizer.py, impact.py) is real.
"""

import math
import random

from constants import KC, STAGES, TYPICAL_YIELD_KG_PER_M2, M2_PER_ACRE
from sources import list_sources, get_source, DEFAULT_SOURCE

FIRST_NAMES = [
    "Murugan", "Kavitha", "Rajesh", "Lakshmi", "Suresh", "Meena",
    "Karthik", "Anitha", "Prabhu", "Devi", "Selvam", "Bhavani",
    "Ganesan", "Priya", "Manikandan", "Saroja", "Velu", "Shanthi",
    "Ramesh", "Kalaivani",
]

# ── Smallholder threshold ────────────────────────────────────────
# India's official definition: a small holding is under 2 hectares
# (20,000 m²), and under 1 ha is "marginal". We use the official line
# rather than an eyeballed number, because this flag drives the
# headline "smallholder harvest kept" figure on the Impact slide and a
# judge can look the definition up.
SMALLHOLDER_AREA_M2 = 20_000          # 2 hectares ≈ 4.94 acres

# ── Farm size distribution ───────────────────────────────────────
# Tamil Nadu holdings are overwhelmingly small: roughly 80% are marginal
# or small. A flat uniform(2000, 20000) would make EVERY farm a
# smallholder under the official threshold, and the smallholder-vs-large
# comparison on the Impact slide would have nothing to compare.
# So we draw from a realistic mix.
SIZE_BANDS = [
    # (weight, min_m2, max_m2)
    (0.55,  2_000,  10_000),   # marginal   (< 1 ha)
    (0.28, 10_000,  20_000),   # small      (1-2 ha)
    (0.12, 20_000,  40_000),   # semi-medium
    (0.05, 40_000, 120_000),   # medium / large
]

# Fraction of farms carrying a fairness debt from previous cycles.
# ⚠ If this is 0, every farm shows debt 0.0, the fairness ledger renders
# blank on every card, and one of our more distinctive features is
# invisible in the demo. Seed it here, not by hand-editing claims.
FAIRNESS_DEBT_SHARE = 0.25
FAIRNESS_DEBT_RANGE = (0.4, 1.8)


# ── Position along the channel ─────────────────────────────
# Every farm sits somewhere between the sluice and the tail. Under a
# working allocation that is a detail; under CURRENT PRACTICE it decides
# who eats, because the channel is filled from the head and whoever is
# past the point where it runs dry gets nothing.
#
# sources.py records command area, not channel geometry, so the run is
# derived: a block of A hectares is about sqrt(A x 10,000) m across, and
# a distributary runs roughly twice that end to end. Fabricated, like
# the rest of this file, but derived from a real recorded figure rather
# than typed in per farm.
def _channel_length_m(source_id):
    """How far the channel runs from head to tail, in metres."""
    ha = get_source(source_id)["command_area_ha"]
    return round(math.sqrt(ha * 10_000) * 2)


def _distance_rng(source_id):
    """A private, stable RNG per source.

    Seeded by the source id so a farm's position never moves between
    reruns. A distance that changed on every rerun would reshuffle who
    the tail-enders are, and the Impact panel would report a different
    number of ruined farms every time the page redrew."""
    return random.Random(f"channel-{source_id}")


def _draw_area(rng):
    """Pick a farm area from the weighted size bands."""
    r = rng.random()
    cumulative = 0.0
    for weight, lo, hi in SIZE_BANDS:
        cumulative += weight
        if r <= cumulative:
            return round(rng.uniform(lo, hi))
    return round(rng.uniform(*SIZE_BANDS[-1][1:]))


def farms_for_source(farms, source_id):
    """Farms served by one tank or canal.

    Tank A never gives water to Tank B's farms. A WUA constituted for
    one command area has no standing over another's — the same
    authority limit that stops us touching private borewells. So
    allocation always runs against ONE source's farm list.
    """
    return [f for f in farms if f.get("source_id") == source_id]


def generate_farms(n, seed=None, source_id=None):
    """
    Generate n fake farms with randomised but realistic attributes.

    Returns a list of dicts, each with:
        farm_id, farmer_name, crop, stage, area_m2, soil_moisture_pct,
        expected_yield_kg, is_smallholder, fairness_debt
    """
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")

    # Use a private RNG instance rather than random.seed(). The global
    # seed leaks into every other module that uses random, so a seeded
    # 100-farm run would silently change behaviour elsewhere.
    rng = random.Random(seed)

    crops = sorted(KC.keys())
    # Spread farms across sources in proportion to command area, so the
    # 72 ha canal carries more farms than the 4 ha village tank. Pass
    # source_id to put every farm under one source instead.
    sources = list_sources()
    weights = [get_source(s)["command_area_ha"] for s in sources]
    total_w = sum(weights)
    farms = []

    for i in range(1, n + 1):
        crop = rng.choice(crops)
        stage = rng.choice(STAGES)
        area_m2 = _draw_area(rng)

        # ⚠ Yield rate is PER CROP, from constants.py.
        # An earlier draft used random.uniform(1.5, 2.5) for every crop,
        # which is roughly right for tomato and wrong by 8x for ragi,
        # 13x for sunflower and 20x for pulses — while under-counting
        # sugarcane by 3x. impact.py sums expected_yield_kg to produce
        # "total food produced", so a flat rate makes the headline
        # number meaningless as soon as the crop mix widens.
        # +/- 15% captures real farm-to-farm variation in management.
        base_rate = TYPICAL_YIELD_KG_PER_M2[crop]
        rate = base_rate * rng.uniform(0.85, 1.15)
        expected_yield_kg = max(1, round(area_m2 * rate))

        # Some farms carry a debt from being short-changed in previous
        # cycles. optimizer.py multiplies priority by (1 + debt).
        fairness_debt = (
            round(rng.uniform(*FAIRNESS_DEBT_RANGE), 2)
            if rng.random() < FAIRNESS_DEBT_SHARE else 0.0
        )

        if source_id is not None:
            src = source_id
        else:
            r, acc = rng.random() * total_w, 0.0
            src = sources[-1]
            for cand, wt in zip(sources, weights):
                acc += wt
                if r <= acc:
                    src = cand
                    break

        farms.append({
            "farm_id": f"F{i:03d}",
            "source_id": src,
            "farmer_name": FIRST_NAMES[(i - 1) % len(FIRST_NAMES)],
            "crop": crop,
            "stage": stage,
            "area_m2": area_m2,
            "soil_moisture_pct": round(rng.uniform(15, 60), 1),
            "expected_yield_kg": expected_yield_kg,
            "is_smallholder": area_m2 < SMALLHOLDER_AREA_M2,
            "fairness_debt": fairness_debt,
            # Somewhere along its own channel. Drawn from this run's rng
            # so a seeded generate_farms() is reproducible.
            "distance_from_head_m": round(
                rng.uniform(5, _channel_length_m(src))),
        })

    return farms


# ── The fixed demo set ───────────────────────────────────────────
# Hand-written rather than generated, so the on-stage numbers are
# identical in rehearsal and in judging. Yields follow the constants
# table exactly; farm_agent computes everything else.
#
# Spread across all four sources so an officer picking any command area
# sees real farms. Sized to the declared command areas:
#     T01 Periya Eri            4 ha  ->   4 farms   THE ON-STAGE SET
#     T02 Kanmoi Chinna Eri    11 ha  ->   7 farms
#     C01 Kalingarayan Canal   72 ha  ->  12 farms
#     C02 Thottiyam Distrib.   41 ha  ->   9 farms
#
# Note the size difference by source, and that it is not decoration.
# Tank command areas are marginal and small holdings; canal command
# areas carry larger farms. Under the official 2 ha smallholder line
# that means the tanks are all smallholders and the canals are mixed —
# which is what finally gives the Impact panel a real smallholder-vs-
# large comparison instead of comparing smallholders to nobody.
#
# fairness_debt is seeded on several farms. If every farm is 0.0 the
# fairness ledger renders blank on every card and the feature is
# invisible in the demo.
_DEMO_SPEC = [
    # (source, id, farmer, crop, stage, area_m2, fairness_debt)

    # ── T01 Periya Eri — the four farms we rehearse on ──
    ("T01", "F001", "Murugan",     "tomato",    "mid",         10_117, 0.0),
    ("T01", "F002", "Kavitha",     "onion",     "late",         8_000, 1.2),
    ("T01", "F003", "Rajesh",      "ragi",      "development",  5_000, 0.0),
    ("T01", "F004", "Lakshmi",     "paddy",     "mid",         12_000, 0.0),

    # ── T02 Kanmoi Chinna Eri — small tank, marginal holdings ──
    ("T02", "F005", "Selvam",      "groundnut", "mid",         14_000, 0.0),
    ("T02", "F006", "Bhavani",     "ragi",      "initial",      9_500, 0.8),
    ("T02", "F007", "Manikandan",  "maize",     "mid",         18_000, 0.0),
    ("T02", "F008", "Saroja",      "onion",     "development", 11_000, 1.5),
    ("T02", "F009", "Velu",        "sorghum",   "mid",         16_500, 0.0),
    ("T02", "F010", "Shanthi",     "bean",      "development", 12_000, 0.0),
    ("T02", "F011", "Ganesan",     "paddy",     "initial",     19_000, 0.4),

    # ── C01 Kalingarayan Branch Canal — larger holdings ──
    ("C01", "F012", "Perumal",     "sugarcane", "mid",         82_000, 0.0),
    ("C01", "F013", "Anitha",      "paddy",     "mid",         64_000, 0.0),
    ("C01", "F014", "Karthik",     "cotton",    "mid",         71_000, 0.0),
    ("C01", "F015", "Vasanthi",    "paddy",     "development", 55_000, 0.9),
    ("C01", "F016", "Subramani",   "sugarcane", "development", 90_000, 0.0),
    ("C01", "F017", "Meena",       "maize",     "late",        38_000, 0.0),
    ("C01", "F018", "Dhanapal",    "tomato",    "mid",         26_000, 0.6),
    ("C01", "F019", "Kalaivani",   "groundnut", "mid",         31_000, 0.0),
    ("C01", "F020", "Ravichandran","paddy",     "late",        58_000, 0.0),
    ("C01", "F021", "Amudha",      "sunflower", "mid",         44_000, 1.1),
    ("C01", "F022", "Nagarajan",   "cotton",    "development", 67_000, 0.0),
    ("C01", "F023", "Sundari",     "ragi",      "mid",         14_000, 0.0),

    # ── C02 Thottiyam Distributary — mixed ──
    ("C02", "F024", "Elango",      "paddy",     "mid",         62_000, 0.0),
    ("C02", "F025", "Poongodi",    "sugarcane", "mid",         74_000, 0.0),
    ("C02", "F026", "Chandran",    "maize",     "mid",         41_000, 0.7),
    ("C02", "F027", "Vijaya",      "onion",     "mid",         29_000, 0.0),
    ("C02", "F028", "Arumugam",    "groundnut", "development", 36_000, 0.0),
    ("C02", "F029", "Malathi",     "bean",      "mid",         22_000, 1.3),
    ("C02", "F030", "Sekar",       "cotton",    "late",        48_000, 0.0),
    ("C02", "F031", "Jothi",       "sorghum",   "development", 33_000, 0.0),
    ("C02", "F032", "Kumaresan",   "tomato",    "development", 27_000, 0.0),
]


def demo_farms(source_id=None):
    """The fixed demo farms. Pass a source_id for just that command area."""
    # Farms are laid out along their own source's channel in the order
    # they are listed above, spaced evenly and then nudged, so the
    # head-to-tail sequence is stable and readable while the metres
    # themselves are not a suspiciously round ruler.
    per_source = {}
    for row in _DEMO_SPEC:
        per_source.setdefault(row[0], []).append(row[1])

    distance = {}
    for sid, fids in per_source.items():
        run = _channel_length_m(sid)
        rng = _distance_rng(sid)
        step = run / (len(fids) + 1)
        for i, fid in enumerate(fids, start=1):
            jitter = rng.uniform(-0.3, 0.3) * step
            distance[fid] = max(5, round(i * step + jitter))

    out = [
        {
            "farm_id": fid,
            "source_id": src,
            "farmer_name": name,
            "crop": crop,
            "stage": stage,
            "area_m2": area,
            "soil_moisture_pct": 35.0,
            "expected_yield_kg": round(area * TYPICAL_YIELD_KG_PER_M2[crop]),
            "is_smallholder": area < SMALLHOLDER_AREA_M2,
            "fairness_debt": debt,
            # Metres from the sluice. Read by impact.head_to_tail_split.
            "distance_from_head_m": distance[fid],
        }
        for src, fid, name, crop, stage, area, debt in _DEMO_SPEC
    ]
    if source_id is not None:
        out = [f for f in out if f["source_id"] == source_id]
    return out


if __name__ == "__main__":
    # manual check — not part of the app
    from sources import list_sources, get_source

    print("=== demo_farms() by source ===")
    for sid in list_sources():
        fs = demo_farms(sid)
        src = get_source(sid)
        ha = sum(f["area_m2"] for f in fs) / 10_000
        small = sum(f["is_smallholder"] for f in fs)
        print(f"\n  {sid}  {src['name']}  —  declared "
              f"{src['command_area_ha']} ha, farms cover {ha:.1f} ha")
        print(f"       {len(fs)} farms, {small} smallholder, "
              f"{len(fs)-small} above 2 ha")
        for f in fs:
            tags = []
            if f["is_smallholder"]:
                tags.append("small")
            if f["fairness_debt"] > 0:
                tags.append(f"debt {f['fairness_debt']}")
            print(f"         {f['farm_id']} {f['farmer_name']:<13}"
                  f"{f['crop']:<10} {f['stage']:<12}"
                  f"{f['area_m2']/M2_PER_ACRE:>6.1f} ac"
                  f"{f['expected_yield_kg']:>9,} kg   {' '.join(tags)}")

    print("\n=== generate_farms(100, seed=42) ===")
    farms = generate_farms(100, seed=42)
    small = sum(f["is_smallholder"] for f in farms)
    debted = sum(f["fairness_debt"] > 0 for f in farms)
    areas = sorted(f["area_m2"] for f in farms)
    print(f"  {len(farms)} farms | {small} smallholders | {debted} with debt")
    print(f"  area {areas[0]:,} - {areas[-1]:,} m2 "
          f"(median {areas[len(areas)//2]:,})")

    print("\n=== reproducibility ===")
    print("  same seed identical:", generate_farms(20, seed=7)
          == generate_farms(20, seed=7))