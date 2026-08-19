"""
farm_agent.py — AquaFair
AGENT 1
Owner: C

Takes: one farm dict (from generate.py) + today's weather
Gives back: one CLAIM dict, matching the team contract exactly.

Runs once per farm. 4 farms -> 4 instances. 100 farms -> 100 instances.
Same function, same tables — this is our scalability proof for Agent 1.

Logic, in order:
  1. Look up Kc for this crop at this growth stage
  2. water_required_L = (ETo * Kc * days - rainfall_mm * effective) * area
  3. survival_minimum_L = water_required_L * SURVIVAL_MIN[crop]
  4. Look up Ky for this crop at its Ky-stage
  5. Write a one-line justification string

1 mm of water over 1 m^2 = 1 litre, so ETo(mm/day) * Kc * days gives the
total mm needed over the period, and multiplying by area_m2 converts
straight to litres. No unit-conversion agent needed.
"""

from constants import (
    KC,
    KY,
    SURVIVAL_MIN,
    FOOD_WEIGHT,
    STAGE_TO_KY_STAGE,
    STAGES,
    CYCLE_DAYS,
    EFFECTIVE_RAIN_FRACTION,
)

# The allocation period, in days, that one claim covers.
#
# ⚠ This MUST come from constants.py, not be redeclared here. It is
# coupled to tank_liters: at 7 days the four demo farms need more water
# for their SURVIVAL MINIMUMS alone than the drought tank holds, so the
# optimizer's Pass 1 becomes infeasible and the contest loop has nothing
# to converge on. An earlier draft of this file hardcoded 7 and silently
# inflated every claim by 75%.
DEFAULT_IRRIGATION_PERIOD_DAYS = CYCLE_DAYS


def build_claim(farm, weather, days=None):
    """
    farm: dict from generate.py
        {farm_id, farmer_name, crop, stage, area_m2,
         soil_moisture_pct, expected_yield_kg, is_smallholder,
         fairness_debt (optional)}
    weather: dict
        {"ETo": float (mm/day), "rainfall_mm": float, "tank_liters": float}
    days: allocation period. Defaults to constants.CYCLE_DAYS.

    Returns a CLAIM dict.
    """
    if days is None:
        days = DEFAULT_IRRIGATION_PERIOD_DAYS

    crop = farm["crop"]
    stage = farm["stage"]
    area_m2 = farm["area_m2"]

    # Fail loudly and usefully rather than with a bare KeyError. This
    # matters because app.py's Add Farm form can submit an unknown crop,
    # and a raw KeyError mid-demo tells the user nothing.
    if crop not in KC:
        raise ValueError(
            f"Unknown crop {crop!r} for farm {farm.get('farm_id')}. "
            f"Known crops: {sorted(KC)}"
        )
    if stage not in STAGES:
        raise ValueError(
            f"Unknown growth stage {stage!r} for farm {farm.get('farm_id')}. "
            f"Known stages: {STAGES}"
        )
    if area_m2 <= 0:
        raise ValueError(
            f"Farm {farm.get('farm_id')} has area_m2 = {area_m2}; must be > 0."
        )

    ky_stage = STAGE_TO_KY_STAGE[stage]

    # 1. Kc lookup
    kc = KC[crop][stage]

    # 2. Water required, in litres, floored at 0 — rain cannot create a
    #    credit, only cancel demand.
    #
    #    ⚠ Rainfall is multiplied by EFFECTIVE_RAIN_FRACTION. Not all
    #    rain reaches the root zone; the rest runs off or percolates
    #    below it. Using raw rainfall over-credits by 25% and, in the
    #    heavy-rain scenario, wrongly zeroes out farms that still need
    #    water — which kills the repooling demo beat.
    eto = weather["ETo"]
    rainfall_mm = weather.get("rainfall_mm", 0)
    effective_rain_mm = rainfall_mm * EFFECTIVE_RAIN_FRACTION

    gross_mm = eto * kc * days
    net_mm = max(0.0, gross_mm - effective_rain_mm)
    water_required_L = round(net_mm * area_m2)

    # 3. Survival minimum
    survival_minimum_L = round(water_required_L * SURVIVAL_MIN[crop])

    # 4. Ky lookup
    ky = KY[crop][ky_stage]

    # 5. Justification — built from water_required_L, never a literal.
    #    If this string is ever hardcoded it will drift away from the
    #    field beside it on the farm card, and judges read cards closely.
    justification = (
        f"{crop.capitalize()} at {ky_stage.replace('_', ' ')}, "
        f"Ky {ky:.2f}, needs {water_required_L:,} L over {days} days"
    )

    return {
        "farm_id": farm["farm_id"],
        # Which tank or canal serves this farm. Carried through so the
        # allocation can never accidentally pool two command areas —
        # Tank A's water does not reach Tank B's farms.
        "source_id": farm.get("source_id"),
        "farmer_name": farm["farmer_name"],
        "crop": crop,
        "stage": stage,
        "ky_stage": ky_stage,
        "area_m2": area_m2,
        "water_required_L": water_required_L,
        "survival_minimum_L": survival_minimum_L,
        "ky": ky,
        "expected_yield_kg": farm["expected_yield_kg"],
        "food_weight": FOOD_WEIGHT[crop],
        # Carried from the farm record, not hardcoded. If every farm is
        # 0.0 the fairness ledger renders blank on every card and the
        # feature is invisible in the demo — seed at least one farm.
        "fairness_debt": float(farm.get("fairness_debt", 0.0)),
        "is_smallholder": farm["is_smallholder"],
        "cycle_days": days,
        # Intermediate values, kept so the dashboard can show its working.
        # A farmer told he is getting less water deserves a traceable
        # reason, and a judge should be able to check the arithmetic
        # without opening the source.
        "kc": kc,
        "eto_used": eto,
        "effective_rain_mm": round(effective_rain_mm, 2),
        "gross_mm": round(gross_mm, 2),
        "net_mm": round(net_mm, 2),
        "justification": justification,
    }


def build_claims(farms, weather, days=None):
    """Convenience wrapper: runs build_claim once per farm in the list."""
    return [build_claim(farm, weather, days) for farm in farms]


if __name__ == "__main__":
    # quick manual check — not part of the app
    from constants import WEATHER_STATES

    demo_farms = [
        {"farm_id": "F001", "farmer_name": "Murugan", "crop": "tomato",
         "stage": "mid", "area_m2": 10117, "expected_yield_kg": 20000,
         "is_smallholder": False, "fairness_debt": 0.0},
        {"farm_id": "F002", "farmer_name": "Kavitha", "crop": "onion",
         "stage": "late", "area_m2": 8000, "expected_yield_kg": 12000,
         "is_smallholder": True, "fairness_debt": 1.2},
        {"farm_id": "F003", "farmer_name": "Rajesh", "crop": "ragi",
         "stage": "development", "area_m2": 5000, "expected_yield_kg": 1250,
         "is_smallholder": True, "fairness_debt": 0.0},
        {"farm_id": "F004", "farmer_name": "Lakshmi", "crop": "paddy",
         "stage": "mid", "area_m2": 12000, "expected_yield_kg": 6000,
         "is_smallholder": False, "fairness_debt": 0.0},
    ]

    for scenario in ("normal", "drought", "rain"):
        weather = WEATHER_STATES[scenario]
        claims = build_claims(demo_farms, weather)
        total = sum(c["water_required_L"] for c in claims)
        survival = sum(c["survival_minimum_L"] for c in claims)
        print(f"\n=== {scenario.upper()} — ETo {weather['ETo']}, "
              f"rain {weather['rainfall_mm']} mm, "
              f"tank {weather['tank_liters']:,} L ===")
        for c in claims:
            print(f"  {c['farm_id']} {c['crop']:<10} "
                  f"need {c['water_required_L']:>8,} L  "
                  f"survival {c['survival_minimum_L']:>8,} L  "
                  f"Ky {c['ky']:.2f}")
        print(f"  TOTAL need {total:,} L | survival {survival:,} L | "
              f"tank {weather['tank_liters']:,} L")

    print("\n=== error handling ===")
    for bad, label in [
        ({**demo_farms[0], "crop": "coconut"}, "unknown crop"),
        ({**demo_farms[0], "stage": "harvest"}, "unknown stage"),
        ({**demo_farms[0], "area_m2": 0}, "zero area"),
    ]:
        try:
            build_claim(bad, WEATHER_STATES["normal"])
            print(f"  {label}: NO ERROR RAISED (bad)")
        except ValueError as e:
            print(f"  {label}: {e}")