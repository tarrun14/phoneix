"""
constants.py — AquaFair
Owner: C

Lookup tables only. No functions. No logic.

═══════════════════════════════════════════════════════════════════════
WHERE THE NUMBERS COME FROM — three tiers. Know which is which.

  [FAO]      Published. Copied from the cited FAO table. Fully citable.
  [DERIVED]  Not published for this crop or stage. Transferred from a
             similar crop, or computed. Defensible by reasoning.
  [ASSUMED]  Our engineering or policy choice. No outside authority.
             Defensible only by saying openly that it IS a choice.

SOURCES — only two publications:

  FAO-56  Allen, Pereira, Raes & Smith (1998). "Crop Evapotranspiration."
          FAO Irrigation & Drainage Paper 56.
          -> Table 12 : Kc for all crops
          -> Table 14 : rice Kc_ini adjusted for climate
          https://www.fao.org/4/x0490e/x0490e0b.htm

  FAO-33  Doorenbos & Kassam (1979). "Yield Response to Water."
          FAO Irrigation & Drainage Paper 33.
          -> stage-wise Ky. FAO-33 itself is not online, but FAO
             republished its stage-wise values here:
             FAO/IAEA, "Deficit Irrigation Practices", Water Reports 22,
             Moutonnet, Table 1 "FAO yield response factors"
             https://www.fao.org/4/y3655e/y3655e04.htm

DO NOT cite "FAO-33 Table 24". Table 24 is in FAO-56, not FAO-33, and
it holds SEASONAL Ky only — one number per crop, no stage breakdown.
That citation was in our early draft and it points at nothing.
═══════════════════════════════════════════════════════════════════════

WHY 10 CROPS AND NOT MORE
  Kc is not the limit — FAO-56 lists about 90 crops.
  Ky is the limit — FAO-33 covers 23 crops, and only 9 of those have
  stage-wise values. Everything else would be numbers we invented.
  We then filtered to crops actually grown in Tamil Nadu command areas.

DELIBERATELY EXCLUDED
  banana      Major TN crop, highest Ky in FAO's table, but a 12-18 month
              perennial. Our model assumes seasonal crops with four
              defined stages. Mixing a year of banana output with a
              season of paddy output makes the impact scorecard
              meaningless. Extending to perennials needs a separate
              yield model, not a table row.
  potato, soybean, winter wheat   Have stage-wise Ky, but not TN crops.
  coconut, turmeric, tapioca, sesame, brinjal, bajra
              Major TN crops with NO Ky in FAO-33 at all. FAO-33 was
              written in 1979 from mostly temperate and Mediterranean
              trials. That gap is a limitation of the source, and the
              honest answer is to say so.
"""

# ── Unit conversion ──────────────────────────────────────────────
M2_PER_ACRE = 4047

# 1 mm of depth over 1 m² = exactly 1 litre.
LITRES_PER_MM_PER_M2 = 1.0

# ── Allocation cycle ─────────────────────────────────────────────
# [ASSUMED] The formula
#     water_needed_L = (ETc * CYCLE_DAYS - rainfall_mm * EFFECTIVE_RAIN)
#                      * area_m2
# needs a cycle length.
#
# ⚠ CYCLE_DAYS IS NOT A FREE PARAMETER. It is coupled to tank_liters.
# Across the 4-farm demo set:
#
#   CYCLE_DAYS   normal deficit   drought deficit   Pass 1 in drought
#        7           43%              73%           INFEASIBLE
#        5           21%              62%           INFEASIBLE
#        4          0.8%              45%           OK
#        3          -32% (surplus)    36%           OK
#
# The pitch says normal is "supply roughly meets demand" and drought is
# a 40-60% deficit. Only 4 gives both. At 7 days even the SURVIVAL
# MINIMUMS exceed the drought tank, so Pass 1 cannot complete and the
# contest loop has nothing to converge on.
CYCLE_DAYS = 4

# [ASSUMED] Fraction of rainfall that reaches the root zone; the rest
# runs off or percolates below. FAO gives climate-specific methods;
# 0.8 is a standard planning shortcut.
EFFECTIVE_RAIN_FRACTION = 0.8


# ═════════════════════════════════════════════════════════════════
# Kc — CROP COEFFICIENT                    ETc = Kc * ETo  [mm/day]
# ═════════════════════════════════════════════════════════════════
# ⚠ FAO-56 Table 12 publishes only THREE Kc values per crop:
#     Kc_ini (initial), Kc_mid (mid-season), Kc_end (end of late season).
#
# There is NO published "development" Kc. FAO-56 Eq. 66 says Kc ramps
# LINEARLY from Kc_ini up to Kc_mid across the development stage.
#
# So our "development" column is [DERIVED] — the midpoint of that ramp.
# It is the correct stage average, but it is our arithmetic, not a
# lookup. Honest answer if asked: "FAO gives three points and a linear
# ramp between them; that number is the ramp midpoint."
#
# Our "late" column = FAO's Kc_end.
KC = {
    #             initial       development     mid           late (= Kc_end)
    "tomato":    {"initial": 0.60, "development": 0.88, "mid": 1.15, "late": 0.80},
    "onion":     {"initial": 0.70, "development": 0.88, "mid": 1.05, "late": 0.75},
    "ragi":      {"initial": 0.30, "development": 0.65, "mid": 1.00, "late": 0.30},
    "paddy":     {"initial": 1.10, "development": 1.15, "mid": 1.20, "late": 0.90},
    "maize":     {"initial": 0.30, "development": 0.75, "mid": 1.20, "late": 0.60},
    "sugarcane": {"initial": 0.40, "development": 0.83, "mid": 1.25, "late": 0.75},
    "cotton":    {"initial": 0.35, "development": 0.75, "mid": 1.15, "late": 0.70},
    "groundnut": {"initial": 0.40, "development": 0.78, "mid": 1.15, "late": 0.60},
    "bean":      {"initial": 0.40, "development": 0.78, "mid": 1.15, "late": 0.35},
    "sunflower": {"initial": 0.35, "development": 0.75, "mid": 1.15, "late": 0.35},
    "sorghum":   {"initial": 0.30, "development": 0.68, "mid": 1.05, "late": 0.55},
}
# Notes, all from FAO-56 Table 12 unless stated:
#   tomato     Solanaceae: 0.60 / 1.15 / 0.70-0.90. We take 0.80, the
#              midpoint of the published Kc_end range.
#   onion      "Onion, dry": 0.70 / 1.05 / 0.75. (Onion GREEN is a
#              separate entry at 0.70/1.00/1.00 — we model dry onion,
#              the TN commercial case.)
#   ragi       Listed as "Millet": 0.30 / 1.00 / 0.30. Table 12 has no
#              finger-millet entry. See the ragi caveat under KY below.
#   paddy      "Rice": Table 12 gives 1.05 / 1.20 / 0.90-0.60.
#              We use Kc_ini = 1.10 from FAO-56 TABLE 14, which adjusts
#              rice Kc_ini by climate: sub-humid + moderate wind = 1.10.
#              That is the correct cell for coastal/deltaic Tamil Nadu.
#              Kc_end 0.90 = harvested at high grain moisture.
#   maize      "Maize, field (grain)": 0.30 / 1.20 / 0.60-0.35.
#              We take 0.60 (harvest at high grain moisture).
#   sugarcane  0.40 / 1.25 / 0.75.
#   cotton     0.35 / 1.15-1.20 / 0.70-0.50. Low end of Kc_mid,
#              high end of Kc_end.
#   groundnut  "Groundnut (Peanut)": 0.40 / 1.15 / 0.60.
#   bean       "Beans, dry and Pulses": 0.40 / 1.15 / 0.35.
#   sunflower  0.35 / 1.0-1.15 / 0.35. We take 1.15 (irrigated, dense
#              stand; the lower value is for rainfed sparse stands).
#   sorghum    "Sorghum - grain": 0.30 / 1.00-1.10 / 0.55. We take the
#              midpoint 1.05 for Kc_mid. This is cholam, a major TN
#              dryland cereal.


# ═════════════════════════════════════════════════════════════════
# Ky — YIELD RESPONSE FACTOR      yield_loss = Ky * (1 - received/needed)
# ═════════════════════════════════════════════════════════════════
# This is what drives priority, so provenance matters most here.
#
# FAO-33 covers 23 crops. Only about 9 have stage-wise values. Rice and
# finger millet are in NEITHER list.
#
# FAO-56 Chapter 8 explicitly permits what we do for the missing ones:
# where Ky is unknown, use Ky = 1, or take the Ky of a crop with similar
# behaviour. Our paddy and ragi rows follow that instruction. Say so.
KY = {
    #             vegetative    flowering      yield_formation  ripening
    "tomato":    {"vegetative": 0.40, "flowering": 1.10, "yield_formation": 0.80, "ripening": 0.40},
    "onion":     {"vegetative": 0.45, "flowering": 0.80, "yield_formation": 0.80, "ripening": 0.30},
    "ragi":      {"vegetative": 0.30, "flowering": 0.90, "yield_formation": 0.70, "ripening": 0.20},
    "paddy":     {"vegetative": 1.00, "flowering": 1.35, "yield_formation": 0.50, "ripening": 0.20},
    "maize":     {"vegetative": 0.40, "flowering": 1.50, "yield_formation": 0.50, "ripening": 0.20},
    "sugarcane": {"vegetative": 0.75, "flowering": 0.50, "yield_formation": 0.50, "ripening": 0.10},
    "cotton":    {"vegetative": 0.20, "flowering": 0.50, "yield_formation": 0.60, "ripening": 0.25},
    "groundnut": {"vegetative": 0.20, "flowering": 0.80, "yield_formation": 0.60, "ripening": 0.20},
    "bean":      {"vegetative": 0.20, "flowering": 1.10, "yield_formation": 0.75, "ripening": 0.20},
    "sunflower": {"vegetative": 0.40, "flowering": 1.00, "yield_formation": 0.80, "ripening": 0.25},
    "sorghum":   {"vegetative": 0.29, "flowering": 1.08, "yield_formation": 0.36, "ripening": 0.14},
}
# Per crop — READ THIS BEFORE ANSWERING A JUDGE:
#
#   groundnut  [FAO] 0.20 / 0.80 / 0.60 / 0.20. Matches the FAO/IAEA
#              table exactly. Seasonal Ky 0.70.
#   bean       [FAO] 0.20 / 1.10 / 0.75 / 0.20. Seasonal Ky 1.15.
#   sugarcane  [FAO] 0.75 / 0.50 / 0.50 / 0.10. Seasonal Ky 1.20.
#              ⚠ CORRECTED — our earlier draft had these shifted one
#              stage left (0.75/0.50/0.10/blank), which dropped the
#              mid value entirely.
#              Note sugarcane peaks in the VEGETATIVE period, not
#              flowering — it is grown for stem biomass, not fruit.
#              That inversion is real. Ripening 0.10 is genuinely
#              near-zero: drying it off at ripening RAISES sucrose.
#   cotton     [FAO] 0.20 / 0.50 / -- / 0.25. Seasonal Ky 0.85.
#              ⚠ ripening CORRECTED 0.20 -> 0.25.
#              yield_formation 0.60 is [DERIVED] — FAO leaves it blank;
#              boll formation is the sensitive window.
#   sunflower  [FAO] 0.40 / 1.00 / 0.80 / --. Seasonal Ky 0.95.
#              ripening 0.25 is [DERIVED]; FAO leaves it blank.
#   maize      [FAO, secondary source] 0.40 / 1.50 / 0.50 / 0.20,
#              seasonal 1.25. The FAO/IAEA table gives maize seasonal
#              only; the stage row is reported as FAO's values in the
#              deficit-irrigation literature and is widely reproduced.
#              THIS IS THE ROW THE DEMO LINE RESTS ON:
#              flowering 1.50 vs ripening 0.20 = 7.5x. Keep maize.
#   tomato     [DERIVED] Seasonal Ky 1.05 is [FAO]. The stage split is
#              widely cited but we could not locate it in an accessible
#              FAO document. Treat as derived.
#   onion      [DERIVED] Seasonal Ky 1.10 is [FAO]. Same situation.
#   paddy      [DERIVED] Rice is absent from FAO-33 entirely. These come
#              from the rice deficit-irrigation literature, where
#              panicle initiation / flowering is the well-documented
#              critical window. FAO-56 Ch.8 sanctions this transfer.
#   sorghum    [DERIVED, but from published numbers] Seasonal Ky 0.90 is
#              [FAO]. FAO gives no stage split for sorghum, so we scaled
#              the MAIZE stage profile by the ratio of the two published
#              seasonal values:  0.90 / 1.25 = 0.72.
#                 maize 0.40 / 1.50 / 0.50 / 0.20
#                 x0.72 -> 0.29 / 1.08 / 0.36 / 0.14
#              Both are C4 cereals with the same flowering-critical
#              behaviour; sorghum is simply less sensitive overall,
#              which is exactly what the seasonal ratio encodes.
#              State the arithmetic openly — it is one line and it is
#              checkable, which is stronger than an unexplained number.
#   ragi       [DERIVED] Finger millet is absent from FAO-33. Nearest
#              published analogue is SORGHUM (seasonal Ky 0.90) — same
#              C4 dryland cereal, similar drought strategy. Sorghum is
#              now IN this table, so a judge can see the analogue rather
#              than take our word for it. Ragi sits slightly below
#              sorghum at flowering (0.90 vs 1.08) because finger millet
#              is the more drought-hardy of the two.
#
# USEFUL FOR THE "WHAT'S YOUR WEAKEST PART" QUESTION:
# The same FAO document compares these published Ky values against
# in-field IAEA measurements across eleven countries. The field values
# averaged about 38% HIGHER — FAO's published numbers UNDERSTATE deficit
# damage (FAO range 0.20-1.15, measured range 0.08-1.75).
# So: "our Ky values are conservative; if anything we under-protect
# crops at their critical stage."


# ═════════════════════════════════════════════════════════════════
# Growth stages, and the Kc-stage -> Ky-stage mapping
# ═════════════════════════════════════════════════════════════════
STAGES = ["initial", "development", "mid", "late"]

# ⚠ KNOWN LIMITATION — raise it yourself before a judge finds it.
#
# Kc uses initial/development/mid/late. Ky uses vegetative/flowering/
# yield_formation/ripening. These are DIFFERENT partitions of the
# season, not two names for the same thing, so any mapping loses
# information. FAO itself is inconsistent here — different FAO documents
# relabel Ky stages onto the Kc scheme in different ways.
#
# With the mapping below, "yield_formation" is UNREACHABLE. Two real
# consequences:
#   1. Every mid-stage crop is scored at its FLOWERING Ky, the highest
#      value in the row. This inflates mid-stage priority. It is
#      conservative — it protects crops at their most critical moment —
#      but it is a bias, and it is ours, not FAO's.
#   2. The yield_formation column is currently dead data. We keep the
#      correct values there so the table stays right if we later split
#      "mid" into two sub-stages.
#
# Do NOT "fix" this by setting yield_formation = flowering. That hides
# the seam instead of documenting it.
STAGE_TO_KY_STAGE = {
    "initial":     "vegetative",
    "development": "vegetative",
    "mid":         "flowering",
    "late":        "ripening",
}


# ═════════════════════════════════════════════════════════════════
# Survival minimum — [ASSUMED], NOT FAO
# ═════════════════════════════════════════════════════════════════
# Fraction of full requirement below which the crop FAILS outright
# rather than yielding proportionally less.
#
# FAO defines no such threshold. The Ky model is linear all the way to
# zero, which is physically wrong at the bottom end — a crop that gets
# 5% of its water does not produce 5% of its yield, it dies. This table
# is our engineering patch for that gap.
#
# Derived from the range used in deficit-irrigation studies, where crops
# are typically held at 40-60% of full requirement. Ordered by drought
# tolerance: ragi toughest, paddy most fragile.
#
# These materially change who gets water. In deployment they would be
# regionally calibrated — which is exactly why they live here as a
# parameter and not as a magic number inside optimizer.py.
SURVIVAL_MIN = {
    "ragi":      0.35,
    "sorghum":   0.35,   # cholam — as drought-hardy as ragi
    "cotton":    0.40,
    "groundnut": 0.40,
    "sunflower": 0.40,
    "maize":     0.45,
    "onion":     0.45,
    "bean":      0.45,
    "tomato":    0.50,
    "sugarcane": 0.50,
    "paddy":     0.55,
}


# ═════════════════════════════════════════════════════════════════
# Food-security weight — [ASSUMED], and openly a POLICY choice
# ═════════════════════════════════════════════════════════════════
# Priority multiplier. Staples that feed people locally rank above cash
# crops. This is a value judgement, not a measurement, and the pitch
# should say so: "the AI optimises; it does not decide the values."
# A WUA could set these differently and the system still works — that
# is the whole point.
FOOD_WEIGHT = {
    "ragi":      1.20,   # staple, high nutrition, drought-resilient
    "paddy":     1.20,   # staple
    "sorghum":   1.15,   # cholam — staple grain and fodder
    "bean":      1.15,   # pulses — protein security
    "maize":     1.10,   # food and fodder
    "tomato":    1.00,
    "groundnut": 0.95,
    "onion":     0.90,
    "sunflower": 0.90,   # edible oil, but not a staple
    "cotton":    0.75,   # non-food cash crop
    "sugarcane": 0.70,   # cash crop, and very water-intensive
}


# ═════════════════════════════════════════════════════════════════
# Yield and price — regional averages, for impact.py
# ═════════════════════════════════════════════════════════════════
# kg per m² at full irrigation. These MUST reproduce expected_yield_kg
# in the demo claims or the impact scorecard will silently disagree
# with the farm cards:
#   tomato 2.0 * 10117 = 20,234 kg   (claim says 20,000)  ok
#   onion  1.5 *  8000 = 12,000 kg                        ok
#   ragi   0.25 * 5000 =  1,250 kg                        ok
#   paddy  0.5 * 12000 =  6,000 kg                        ok
TYPICAL_YIELD_KG_PER_M2 = {
    "tomato":    2.00,   # ~20 t/ha
    "onion":     1.50,   # ~15 t/ha
    "ragi":      0.25,   # ~2.5 t/ha
    "paddy":     0.50,   # ~5 t/ha
    "maize":     0.60,   # ~6 t/ha
    "sugarcane": 7.00,   # ~70 t/ha (conservative; TN often exceeds 100)
    "cotton":    0.25,   # ~2.5 t/ha seed cotton
    "groundnut": 0.20,   # ~2 t/ha
    "bean":      0.10,   # ~1 t/ha dry pulses
    "sunflower": 0.15,   # ~1.5 t/ha seed
    "sorghum":   0.30,   # ~3 t/ha
}

# Rupees per kg. Anchored to Minimum Support Price where one exists
# (2025-26 kharif season) because MSP is a public number a judge can
# check, unlike a volatile mandi spot price.
#   paddy      MSP Rs 2,369/qtl  -> Rs 23.7/kg
#   ragi       MSP Rs 4,886/qtl  -> Rs 48.9/kg
#   groundnut  MSP ~Rs 7,263/qtl -> Rs 72.6/kg
#   maize      MSP ~Rs 2,400/qtl -> Rs 24/kg
#   cotton     MSP ~Rs 7,700/qtl -> Rs 77/kg (medium staple)
#   sunflower  MSP ~Rs 7,700/qtl -> Rs 77/kg
#   bean       pulses MSP varies by type; tur ~Rs 8,000/qtl -> Rs 80/kg
#   sorghum    jowar hybrid MSP ~Rs 3,700/qtl -> Rs 37/kg
# Tomato and onion have NO MSP. These are indicative TN mandi averages
# and are genuinely volatile — tomato has traded Rs 5 to Rs 100/kg
# inside a single year. Flag that if the economics are questioned.
MARKET_PRICE_PER_KG = {
    "tomato":    15,     # no MSP, highly volatile
    "onion":     20,     # no MSP, highly volatile
    "ragi":      49,
    "paddy":     24,
    "maize":     24,
    "sugarcane": 3.4,    # FRP ~Rs 340/qtl
    "cotton":    77,
    "groundnut": 73,
    "bean":      80,
    "sunflower": 77,
    "sorghum":   37,
}


# ═════════════════════════════════════════════════════════════════
# Weather / scenario presets — [ASSUMED], tuned for the demo
# ═════════════════════════════════════════════════════════════════
# tank_liters is calibrated for REFERENCE_FARM_COUNT farms. Scale it
# with n_farms (see impact.run_scenario) so 100-farm runs are not
# artificially starved by a tank sized for a 4-farm demo.
REFERENCE_FARM_COUNT = 10

# DROUGHT moves BOTH levers on purpose: supply falls 700k -> 480k AND
# ETo rises 5.0 -> 6.2 so demand climbs at the same time. That is what
# produces the ~45% deficit. Do not "simplify" it to a supply cut — the
# demand side is half the story.
#
# ⚠ Drought tank is 480k, NOT the 420k in our first draft. At
# CYCLE_DAYS = 4 the four demo farms need 435,854 L just to reach their
# SURVIVAL MINIMUMS in drought. A 420k tank is below that, so Pass 1 is
# mathematically infeasible: every farm ends up under its floor, every
# farm contests, and the loop burns all 3 rounds without converging.
# That is a hang in front of judges, not drama.
# 480k leaves 44,146 L for Pass 2 to fight over — tight enough that
# priority ordering visibly matters, feasible enough that the loop
# terminates.
# IF A CHANGES THE SURVIVAL MINIMUMS, RECHECK THIS NUMBER.
#
# ⚠ RAIN is 12 mm, NOT the 25 mm in our first draft. At a 4-day cycle
# no demo crop needs more than ~19 mm, so 25 mm (20 mm effective) zeroes
# out EVERY farm at once and the dashboard goes blank. 12 mm (9.6 mm
# effective) gives the intended beat:
#     ragi    10.4 mm gross ->  0.8 mm net   demand COLLAPSES
#     onion   12.0 mm gross ->  2.4 mm net   sharply reduced
#     tomato  18.4 mm gross ->  8.8 mm net   still thirsty
#     paddy   19.2 mm gross ->  9.6 mm net   still thirsty
# One farm drops out, its water is freed, the coordinator repools it.
WEATHER_STATES = {
    "normal":  {"ETo": 5.0, "rainfall_mm":  0, "tank_liters": 700_000},
    "drought": {"ETo": 6.2, "rainfall_mm":  0, "tank_liters": 480_000},
    "rain":    {"ETo": 4.0, "rainfall_mm": 12, "tank_liters": 700_000},
}

# The dashboard opens on these readings.
#
# DROUGHT, deliberately: the demo should open on the case the app exists
# for, not on a quiet week.
#
# ⚠ The original reason for this ("normal is a 1% shortfall, every bar
# full, nothing contested") is no longer accurate, and the corrected
# figures are a better argument than the old ones. Since the tank volume
# now comes from sources.py rather than from the preset below, NORMAL on
# Periya Eri is already a 20.6% shortfall with F001 contesting over two
# rounds. Drought is 36% across three rounds with two farms contesting —
# still the stronger opening, but not the difference between nothing and
# something.
#
# ⚠ This only sets ETo and RAINFALL. The water volume comes from the
# selected command area (sources.deliverable_water_L), so changing this
# cannot change how much water the demo starts with.
#
# ⚠ DEMO SCRIPT: the 5-minute script runs Normal -> Drought -> Heavy
# rain, and watching the numbers move on that first click is one of the
# better beats. Opening on drought means pressing Normal first to get it
# back. Set this to "normal" if you would rather keep that transition.
DEFAULT_WEATHER = "drought"


# ═════════════════════════════════════════════════════════════════
# Crop-failure compensation — [FAO? no. GOVERNMENT NORM.]
# ═════════════════════════════════════════════════════════════════
# What the state owes a farmer whose crop fails outright, per acre.
# impact.py costs every farm below its survival minimum at this rate,
# so the Impact panel can show what each policy would have to pay.
#
# SOURCE: National Disaster Response Fund norms. Crop loss compensation
# is Rs 17,000 per hectare for IRRIGATED land (Rs 8,500 rain-fed,
# Rs 22,500 perennial). A canal or tank command area is irrigated by
# definition, so 17,000/ha is the right cell.
#
#     Rs 17,000 / hectare  ->  Rs 17,000 / 2.471 acres  =  Rs 6,880/acre
#
# This is deliberately the CONSERVATIVE figure. Tamil Nadu crop
# insurance pays up to Rs 26,000/acre for paddy, Rs 20,000 for millets
# and Rs 12,000 for pulses, and farmer associations have reported state
# drought relief around Rs 15,000/acre. Using the NDRF floor means the
# compensation AquaFair avoids is understated rather than inflated —
# if the number is wrong, it is wrong in the direction that weakens our
# own case, which is the only safe direction for it to be wrong in.
#
# ⚠ NDRF also caps a claim at two hectares per farmer. We do not model
# the cap, so the figure for a large holding is an upper bound on what
# would actually be paid. Say so if the economics are questioned.
COMPENSATION_PER_ACRE_RUPEES = 6_880


# Tank and canal records live in sources.py, NOT here.
# constants.py holds published FAO reference data — citable, unchanging,
# the same in every district. Tank storage is a daily gauge reading for
# one district that nobody publishes. Different lifecycle, different
# file, and the database swap should not touch a file full of FAO
# tables. See sources.load_sources().


# ═════════════════════════════════════════════════════════════════
# Policy modes
# ═════════════════════════════════════════════════════════════════
POLICY_MODES = ["yield_max", "equity", "emergency"]
DEFAULT_POLICY = "equity"    # app.py must open here, not on yield_max


# ═════════════════════════════════════════════════════════════════
# Integrity check — cheap, catches the classic merge failure
# ═════════════════════════════════════════════════════════════════
# If someone adds a crop to one table and forgets another, this fires at
# import time instead of KeyError-ing mid-demo in front of judges.
_TABLES = {
    "KC": KC,
    "KY": KY,
    "SURVIVAL_MIN": SURVIVAL_MIN,
    "FOOD_WEIGHT": FOOD_WEIGHT,
    "TYPICAL_YIELD_KG_PER_M2": TYPICAL_YIELD_KG_PER_M2,
    "MARKET_PRICE_PER_KG": MARKET_PRICE_PER_KG,
}
CROPS = sorted(KC.keys())
KY_STAGES = ["vegetative", "flowering", "yield_formation", "ripening"]

for _name, _table in _TABLES.items():
    _missing = set(CROPS) - set(_table.keys())
    _extra = set(_table.keys()) - set(CROPS)
    assert not _missing, f"{_name} is missing crops: {sorted(_missing)}"
    assert not _extra, f"{_name} has unknown crops: {sorted(_extra)}"

for _crop in CROPS:
    assert set(KC[_crop]) == set(STAGES), f"KC[{_crop}] stage keys wrong"
    assert set(KY[_crop]) == set(KY_STAGES), f"KY[{_crop}] stage keys wrong"
    assert 0.0 < SURVIVAL_MIN[_crop] < 1.0, f"SURVIVAL_MIN[{_crop}] out of range"

assert set(STAGE_TO_KY_STAGE) == set(STAGES)
assert set(STAGE_TO_KY_STAGE.values()) <= set(KY_STAGES)