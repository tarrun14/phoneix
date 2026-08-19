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

import csv
import math
import random
from pathlib import Path

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


# ── Position along the channel ───────────────────────────────────
# Every farm sits somewhere between the sluice and the tail. Under a
# working allocation that is a detail; under CURRENT PRACTICE it decides
# who eats, because the channel is filled from the head and whoever is
# past the point where it runs dry gets nothing.
#
# sources.py records command area, not channel geometry, so the run is
# DERIVED rather than typed: a block of A hectares is about
# sqrt(A x 10,000) m across, and a distributary runs roughly twice that
# end to end. Fabricated like the rest of this file, but derived from a
# real recorded figure — so editing a command area in the database moves
# the channel with it instead of leaving a hardcoded span behind.
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

    # ⚠ EVERY SOURCE GETS AT LEAST ONE FARM.
    # Weighting by command area is right — a 72 ha canal should carry
    # more farms than a 4 ha village tank — but T01 is 3% of the
    # district, so a 100-farm draw can legitimately give it zero. The
    # dashboard then shows "no farms registered under Periya Eri" and
    # nothing else, which on stage looks exactly like a broken Load 100
    # button. Seed one farm per source first, then weight the rest.
    seeded = list(sources) if source_id is None else []
    if len(seeded) > n:
        seeded = seeded[:n]

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
        elif seeded:
            # One each, in order, before anything is weighted.
            src = seeded.pop(0)
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
            # so a seeded generate_farms() stays reproducible.
            "distance_from_head_m": round(
                rng.uniform(5, _channel_length_m(src))),
        })

    return farms


# ── The fixed demo set ───────────────────────────────────────────
# The farms themselves live in demo_farms.csv, NOT in this file.
#
# WHY A CSV
# A farm record is a row: source, id, farmer, crop, stage, area, debt.
# Seven columns, no nesting. Keeping it as a spreadsheet means anyone on
# the team can add or edit a demo farm without touching Python, and a
# diff shows one changed row instead of a changed source file.
#
# ⚠ ONLY THE INPUTS ARE IN THE CSV.
# expected_yield_kg and is_smallholder are DERIVED in demo_farms() from
# constants.py. Putting a yield in the CSV is exactly the drift that
# broke the first fake_claims.py: a typed number and a computed number
# disagreeing, with no way to tell which was right. If the yield rate in
# constants.py changes, every demo farm follows automatically.
#
# The generator below is NOT data and stays in Python — you cannot put
# weighted size bands and per-crop variance in a spreadsheet.
#
# Sized to the declared command areas:
#     T01 Periya Eri            4 ha  ->   4 farms   THE ON-STAGE SET
#     T02 Kanmoi Chinna Eri    11 ha  ->   7 farms
#     C01 Kalingarayan Canal   72 ha  ->  12 farms
#     C02 Thottiyam Distrib.   41 ha  ->   9 farms
#
# Note the size difference by source, and that it is not decoration.
# Tank command areas are marginal and small holdings; canal command
# areas carry larger farms. Under the official 2 ha smallholder line
# that means the tanks are all smallholders and the canals are mixed —
# which is what gives the Impact panel a real smallholder-versus-large
# comparison instead of comparing smallholders to nobody.
#
# fairness_debt is seeded on several rows. If every farm were 0.0 the
# fairness ledger would render blank on every card and the feature
# would be invisible in the demo.

# Resolved against THIS file, not the working directory. `streamlit run
# app.py` and `python main.py` can be launched from anywhere, and a
# relative "demo_farms.csv" would only resolve for one of them.
DEMO_FARMS_CSV = Path(__file__).with_name("demo_farms.csv")

# ⚠ distance_from_head_m is NOT here. It is computed in demo_farms()
# from the source's command area, so a channel position cannot drift
# from the tank record it is derived from — the same reason
# expected_yield_kg is not in the CSV either.
DEMO_CSV_FIELDS = ["source_id", "farm_id", "farmer_name", "crop",
                   "stage", "area_m2", "fairness_debt"]


def load_demo_spec(path=None):
    """Read the demo farms from CSV.

    Validates as it reads. A malformed row should fail here with a line
    number and a reason, not three modules downstream with a KeyError
    that names a crop nobody typed.
    """
    path = Path(path) if path else DEMO_FARMS_CSV
    if not path.exists():
        raise FileNotFoundError(
            f"{path.name} not found next to generate.py. It holds the 32 "
            f"demo farms; without it there is no on-stage set.")

    spec = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = set(DEMO_CSV_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{path.name} is missing column(s): {sorted(missing)}")

        for line, row in enumerate(reader, start=2):
            crop = row["crop"].strip()
            stage = row["stage"].strip()
            if crop not in KC:
                raise ValueError(
                    f"{path.name} line {line}: unknown crop {crop!r}. "
                    f"Known: {sorted(KC)}")
            if stage not in STAGES:
                raise ValueError(
                    f"{path.name} line {line}: unknown stage {stage!r}. "
                    f"Known: {STAGES}")
            try:
                area = int(row["area_m2"])
                debt = float(row["fairness_debt"])
            except ValueError as exc:
                raise ValueError(
                    f"{path.name} line {line}: {exc}") from exc
            if area <= 0:
                raise ValueError(
                    f"{path.name} line {line}: area_m2 must be > 0")

            spec.append({
                "source_id": row["source_id"].strip(),
                "farm_id": row["farm_id"].strip(),
                "farmer_name": row["farmer_name"].strip(),
                "crop": crop,
                "stage": stage,
                "area_m2": area,
                "fairness_debt": debt,
            })

    ids = [r["farm_id"] for r in spec]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"{path.name}: duplicate farm_id(s): {dupes}")
    return spec


def demo_farms(source_id=None):
    """The fixed demo farms. Pass a source_id for just that command area.

    Inputs come from demo_farms.csv; expected_yield_kg, is_smallholder
    and distance_from_head_m are derived here so they can never drift
    from constants.py or from the tank record.

    Farms are laid out along their own source's channel in the order
    they are listed in the CSV, spaced evenly and then nudged, so the
    head-to-tail sequence is stable and readable while the metres
    themselves are not a suspiciously round ruler."""
    spec = load_demo_spec()

    per_source = {}
    for r in spec:
        per_source.setdefault(r["source_id"], []).append(r["farm_id"])

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
            "farm_id": r["farm_id"],
            "source_id": r["source_id"],
            "farmer_name": r["farmer_name"],
            "crop": r["crop"],
            "stage": r["stage"],
            "area_m2": r["area_m2"],
            "soil_moisture_pct": 35.0,
            "expected_yield_kg": round(
                r["area_m2"] * TYPICAL_YIELD_KG_PER_M2[r["crop"]]),
            "is_smallholder": r["area_m2"] < SMALLHOLDER_AREA_M2,
            "fairness_debt": r["fairness_debt"],
            # Metres from the sluice. Read by head_to_tail_split().
            "distance_from_head_m": distance[r["farm_id"]],
        }
        for r in spec
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