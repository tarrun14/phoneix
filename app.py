"""
app.py — AquaFair
THE DASHBOARD
Owner: B (Shyam M)

Run:  streamlit run app.py

ARCHITECTURE RULE FOR THIS FILE
Every panel is a function that takes its data as arguments. No render
function reaches out to a global, a module-level list, or the engine.
`compute()` below is the ONLY place that calls the engine. If the engine
changes shape, one function changes and the layout does not move.

  compute(farms, weather, mode)  ->  one dict
        |
        +-- render_top_bar(out, source)
        +-- render_condition_badge(...)
        +-- render_farm_cards(claims, allocation, limit)
        +-- render_activity_log(log)
        +-- render_impact(scorecard)
        +-- render_agent_trace(out, source)   the "show me it isn't
                                              hardcoded" panel

State lives in st.session_state: the farm list, the selected command
area, the three readings, and the policy. Everything on screen is
derived from those by a fresh compute() on every rerun. Nothing is
cached, nothing is stale, and no number is ever written by hand.

ONE COMMAND AREA AT A TIME
Farms belong to a tank or canal and never compete across them. Tank A's
water does not reach Tank B's farms, and no Water User Association has
the authority to move it. `served` in main() is filtered BEFORE
compute() is called, so the engine is never even shown the other farms.
"""

from datetime import datetime

import streamlit as st

from constants import (M2_PER_ACRE, WEATHER_STATES, KC, STAGES,
                       DEFAULT_WEATHER, CYCLE_DAYS, EFFECTIVE_RAIN_FRACTION)
from coordinator import (CONTEST_YIELD_LOSS_PCT, ESCALATION_FACTOR,
                         MAX_ROUNDS)
from generate import (demo_farms, generate_farms, farms_for_source,
                      SMALLHOLDER_AREA_M2)
from impact import compute_actual_yield, run_scenario
from optimizer import SMALLHOLDER_BOOST
from sources import (list_sources, get_source, deliverable_water_L,
                     conveyance_loss_L, DEFAULT_SOURCE)

# ══════════════════════════════════════════════════════════════════
# Palette — petrol blue for water, ochre for scarcity, clay for loss
# ══════════════════════════════════════════════════════════════════
INK      = "#12303B"   # deep petrol, text and structure
WATER    = "#2E7D96"   # allocated water
FLOOR    = "#14505F"   # survival floor — darker, denser
SURPLUS  = "#7FB6C7"   # surplus above the floor — lighter
                       # (bars are coloured by outcome now, see BAR_*;
                       #  these two remain the reference tones)
SHORT    = "#E8E2D6"   # the gap: what the farm asked for and didn't get
OCHRE    = "#C77D2E"   # contested
CLAY     = "#A8412F"   # crop lost
SAGE     = "#5C7A5A"   # healthy
STORM    = "#4F6B74"   # the weather agent, reading the sky
PAPER    = "#FBF9F5"

SCENARIOS = {
    "normal":  ("Normal",     "Supply roughly meets demand"),
    "drought": ("Drought",    "Less water, and crops want more of it"),
    "rain":    ("Heavy rain", "Demand collapses, water is freed"),
}

MODES = {
    "equity":    ("Equity-constrained", "Survival floor for every farm, then priority"),
    "yield_max": ("Maximise yield",     "No floor. Biggest crop first."),
    "emergency": ("Emergency split",    "Floor for everyone, then share equally"),
}

# Bar colour by outcome, not by farm. Scanning the column should tell
# you who is in trouble before you read a word. Each pair is (survival
# floor, surplus) so the two-pass structure stays visible inside the
# colour: the darker half is the floor, the lighter half is surplus.
FULL_SHARE_PCT  = 0.95    # at or above this, the farm got what it asked
PART_SHARE_PCT  = 0.60    # below this it is badly short
BAR_GREEN = ("#4A6B48", "#8FA98D")
BAR_AMBER = ("#B06E22", "#E0AE74")
BAR_RED   = ("#963A2A", "#C9836F")

# ── The whole visual system ─────────────────────────────────────
# Two inks, five sizes, one family, and three outcome colours. Anything
# that is not an outcome is INK or GREY — a dashboard that colours
# decoration has nothing left to say when a farm is actually failing.
#
# The palette block above keeps its original tones: they are still the
# reference the outcome pairs were mixed from, and the condition badge
# still reads from them.
FONT_SANS = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
             "'Helvetica Neue', Arial, sans-serif")
T_TITLE = "28px"    # the page
T_HEAD  = "20px"    # section headings
T_CARD  = "17px"    # a farm's crop and stage
T_BODY  = "14px"    # sentences
T_SMALL = "12px"    # IDs, labels, notes, expander summaries
GREY    = "#77726B"   # the one secondary ink
LINE    = "#E4DED3"   # hairlines and card borders
TINT    = "#F1EDE6"   # the one neutral fill
OK      = BAR_GREEN[0]    # outcome green, and nothing else
WARN    = BAR_AMBER[0]    # outcome amber, and nothing else
BAD     = BAR_RED[0]      # outcome red, and nothing else

# Ky threshold, technical band, plain words for the card, colour.
# The card shows the plain words. "Ky 1.35 Critical" is true and
# useless to a farmer; the number stays, one expander away.
KY_BANDS = [
    (1.20, "Critical",  "Very sensitive to shortage now", CLAY),
    (0.80, "Sensitive", "Sensitive to shortage now",      OCHRE),
    (0.40, "Moderate",  "Moderately sensitive",           WATER),
    (0.00, "Hardy",     "Hardy right now",                SAGE),
]

# ── Condition thresholds ─────────────────────────────────────────
# There is no "current scenario" in this app. There are three readings,
# and this is the only place they turn into a word. Every threshold is a
# number a judge can check against the panel beside it.
HEAVY_RAIN_MM    = 15.0   # effective mm in one cycle — demand collapses
# ⚠ The "Heavy rain" preset is 12 mm gross = 9.6 mm effective, so it
# classifies as NORMAL (with a large surplus), not HEAVY RAIN. That is
# the classifier working, not failing: 12 mm was chosen in constants.py
# because 25 mm zeroes out every farm and blanks the dashboard. To make
# the preset land on HEAVY RAIN, move this to 9.0 or raise the preset.
DRY_ETo          = 6.0    # mm/day at or above this, the air is taking it
DRY_RAIN_MM      = 5.0    # effective mm below this, rain is not helping
STRESS_SHORT_PCT = 30.0   # tank misses total demand by this much or more
SHORT_ALARM_PCT  = 20.0   # above this the headline shortfall turns red

CONDITION_COLOURS = {
    # WATER is the one colour on the page that is not an outcome tone.
    # It stays because heavy rain is not a good or a bad outcome, it is
    # a different weather, and green would read as "all clear".
    "HEAVY RAIN":   WATER,
    "DROUGHT":      BAD,
    "WATER STRESS": WARN,
    "DRY SPELL":    WARN,
    "NORMAL":       OK,
}


# ══════════════════════════════════════════════════════════════════
# THE SEAM — the only function in this file that calls the engine
# ══════════════════════════════════════════════════════════════════

def compute(farms, weather, mode, scale_tank=True):
    """Run the full pipeline. Returns the dict every panel renders from.

    `weather` is a preset key OR a dict of live readings — the engine
    takes either, so nothing here is tied to the three presets.

    `farms` must already be filtered to ONE command area. This function
    does not filter; main() does, before calling.

    On failure, returns an error marker rather than letting a traceback
    take over the screen mid-demo."""
    try:
        return run_scenario(farms, weather, mode=mode, scale_tank=scale_tank)
    except Exception as exc:            # noqa: BLE001 — demo safety net
        return {"error": str(exc)}


# ══════════════════════════════════════════════════════════════════
# Small helpers
# ══════════════════════════════════════════════════════════════════

def bar_colours(a):
    """(floor colour, surplus colour, plain words) for one farm's bar.

    A contested farm is red whatever its percentage: the coordinator
    escalated it because the crop is taking real damage, and a bar that
    reads "fine" under a farm that spent three rounds fighting for water
    would be the dashboard lying quietly."""
    if a["contested"] or a["satisfaction"] < PART_SHARE_PCT:
        return BAR_RED + ("badly short",)
    if a["satisfaction"] < FULL_SHARE_PCT:
        return BAR_AMBER + ("partly short",)
    return BAR_GREEN + ("full share",)


def ky_band(ky):
    """(technical band, plain words, colour) for one crop's Ky."""
    for threshold, label, plain, colour in KY_BANDS:
        if ky >= threshold:
            return label, plain, colour
    return "Hardy", "Hardy right now", SAGE


def acres(m2):
    return m2 / M2_PER_ACRE


def growth_stage(claim):
    """The growth stage in one word: 'Flowering'. The half of
    stage_label a farmer recognises without translating."""
    return claim["ky_stage"].replace("_", " ").capitalize()


def stage_label(claim):
    """'Mid-season, flowering' — reads better than a raw enum."""
    return f"{claim['stage'].replace('_', ' ').capitalize()}, " \
           f"{claim['ky_stage'].replace('_', ' ')}"


# ══════════════════════════════════════════════════════════════════
# PANELS
# ══════════════════════════════════════════════════════════════════

def shortfall_pct(out):
    """How far the pool falls short of total demand, in percent.

    Negative means supply exceeds demand. The top bar and the condition
    badge both read this, so there is one definition of the number and
    the badge can never disagree with the metric beside it."""
    demand = sum(c["water_required_L"] for c in out["claims"])
    if demand <= 0:
        return 0.0
    return (1 - out["tank_L"] / demand) * 100


def classify_conditions(eto, rainfall_mm, shortfall):
    """Turn this cycle's readings into a condition label.

    Pure: the same three numbers always give the same word, and nothing
    else can set it. main() calls this on every rerun and stores no
    result, so a label cannot outlive the readings that produced it —
    which is exactly how the old scenario buttons went stale.

    The order of the tests is the definition: rain overrides everything,
    then heat and shortage together, then either one alone.

    Returns (label, colour, why) where `why` quotes the values used."""
    eff_rain = rainfall_mm * EFFECTIVE_RAIN_FRACTION

    if eff_rain >= HEAVY_RAIN_MM:
        label = "HEAVY RAIN"
    elif (eto >= DRY_ETo and eff_rain < DRY_RAIN_MM
            and shortfall >= STRESS_SHORT_PCT):
        label = "DROUGHT"
    elif shortfall >= STRESS_SHORT_PCT:
        # Short of water without the heat driving it: the source is the
        # problem, not the sky.
        label = "WATER STRESS"
    elif eto >= DRY_ETo:
        # Thirsty crops, but the source is still covering them.
        label = "DRY SPELL"
    else:
        label = "NORMAL"

    gap = (f"{shortfall:.0f}% shortfall" if shortfall > 0
           else f"{abs(shortfall):.0f}% surplus")
    why = (f"ETo {eto:.1f} mm/day, {rainfall_mm:.0f}mm rain "
           f"({eff_rain:.1f}mm effective), {gap}")
    return label, CONDITION_COLOURS[label], why


def inject_style():
    """One family, one type scale, and the card/expander pairing.

    The two rules that matter: st.code and the activity log keep their
    monospace, and a farm card plus its 'why this amount' expander are
    wrapped in a keyed container so the gap can go OUTSIDE the pair and
    come off the seam INSIDE it. Streamlit's default element gap makes
    every card look equally far from every other thing on the page."""
    st.markdown(f"""<style>
      html, body, .stApp, button, input, textarea, select,
      [data-testid="stMarkdownContainer"] {{
          font-family: {FONT_SANS};
      }}
      /* the agent log and the trace stay monospace */
      code, pre, [data-testid="stCode"], [data-testid="stCode"] * {{
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace !important;
      }}
      [data-testid="stMarkdownContainer"] p {{
          font-size: {T_BODY}; color: {INK};
      }}
      [data-testid="stCaptionContainer"] p {{
          font-size: {T_SMALL}; color: {GREY};
      }}
      [data-testid="stExpander"] summary p {{
          font-size: {T_SMALL}; color: {GREY}; font-weight: 500;
      }}
      [data-testid="stExpander"] details {{ border-color: {LINE}; }}

      /* Streamlit paints its primary button and its checkbox tick in
         the theme accent, which put two more colours on a page whose
         rule is that colour means outcome. Dark neutral fill is just as
         prominent against paper and says nothing about a farm. */
      [data-testid="stBaseButton-primary"] {{
          background: {INK}; border-color: {INK};
          font-weight: 600; font-size: {T_BODY};
      }}
      [data-testid="stBaseButton-primary"],
      [data-testid="stBaseButton-primary"] p,
      [data-testid="stBaseButton-primary"] [data-testid="stMarkdownContainer"] p {{
          color: {PAPER} !important;
      }}
      [data-testid="stBaseButton-primary"]:hover {{
          background: {FLOOR}; border-color: {FLOOR};
      }}
      [data-testid="stCheckbox"] label[data-selected="true"] svg {{
          fill: {INK};
      }}
      [data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type {{
          background: {INK} !important; border-color: {INK} !important;
      }}

      /* The log fills the column, and its own box fills the container.
         The cap is what keeps that honest at 100 farms, where the log
         runs to a few hundred entries: without it the page grew to
         twelve thousand pixels to accommodate a panel nobody scrolls
         that far into. Capped, it scrolls inside its own box and the
         farm list sets the page height again. */
      [class*="st-key-logbox"] {{ max-height: 78vh; }}
      [class*="st-key-logbox"] > div,
      [class*="st-key-logbox"] [data-testid="stMarkdownContainer"] {{
          height: 100%;
      }}

      /* a card and its expander are one unit */
      [class*="st-key-farmcard"] {{ margin-bottom: 20px; }}
      [class*="st-key-farmcard"] [data-testid="stExpander"] {{
          margin-top: -14px;
      }}
      [class*="st-key-farmcard"] details {{
          border-top-left-radius: 0; border-top-right-radius: 0;
      }}
    </style>""", unsafe_allow_html=True)


def section(text):
    """Every section heading on the page, at one size."""
    st.markdown(
        f"<div style='font-size:{T_HEAD};font-weight:700;color:{INK};"
        f"letter-spacing:-0.01em;margin:0 0 2px 0;'>{text}</div>",
        unsafe_allow_html=True)


def detail_table(rows):
    """(label, value, note) rows as one quiet table. Used by everything
    that lives behind an expander, so the detail views match."""
    html = "".join(
        f"<tr style='border-bottom:1px solid {LINE};'>"
        f"<td style='padding:7px 10px 7px 0;color:{GREY};'>{label}</td>"
        f"<td style='padding:7px 10px;text-align:right;font-weight:600;"
        f"color:{INK};white-space:nowrap;'>{value}</td>"
        f"<td style='padding:7px 0 7px 10px;color:{GREY};"
        f"font-size:{T_SMALL};'>{note}</td></tr>"
        for label, value, note in rows)
    st.markdown(
        f"<table style='width:100%;border-collapse:collapse;"
        f"font-size:{T_BODY};'>{html}</table>", unsafe_allow_html=True)


def render_condition_badge(label, colour, why):
    """The label and, under it, the arithmetic that produced it. If the
    two ever disagree, the classifier is wrong — not the display."""
    st.markdown(
        f"<div style='margin:10px 0 2px 0;'>"
        f"<span style='background:{colour};color:{PAPER};font-size:{T_SMALL};"
        f"font-weight:700;letter-spacing:0.09em;padding:5px 14px;"
        f"border-radius:999px;'>{label}</span></div>"
        f"<div style='color:{GREY};font-size:{T_SMALL};margin-top:8px;'>"
        f"{why}</div>", unsafe_allow_html=True)


def render_top_bar(out, source):
    """Three numbers: what there is, what is wanted, what is missing.

    Farm count and the allocated total were here and are now in the
    readings expander — one repeats the sidebar, and the other is
    always the whole pool, so neither changes what a reader does next.
    Built as markup rather than st.metric because the shortfall has to
    be the biggest thing on the page and metrics are all one size.

    The command area is named above the numbers: every figure on this
    page belongs to one tank or canal, and a reader who has just
    switched sources needs to see which one without looking away."""
    claims = out["claims"]
    tank = out["tank_L"]
    demand = sum(c["water_required_L"] for c in claims)
    gap = shortfall_pct(out)

    # A negative deficit is a surplus. Showing "-208%" reads as broken.
    if demand <= 0:
        value, note, colour = "None", "no demand this cycle", OK
    elif gap > 0:
        value = f"{gap:.0f}%"
        note = "of what the farms need is missing"
        colour = BAD if gap > SHORT_ALARM_PCT else INK
    else:
        value, colour = "None", OK
        note = ("the source covers every claim twice over" if -gap >= 100
                else "the source covers every claim")

    def small(label, value):
        return (f"<div>"
                f"<div style='font-size:{T_SMALL};color:{GREY};"
                f"letter-spacing:0.02em;'>{label}</div>"
                f"<div style='font-size:{T_HEAD};font-weight:600;color:{INK};"
                f"line-height:1.3;'>{value}</div></div>")

    st.markdown(
        f"<div style='font-size:{T_SMALL};color:{GREY};margin:2px 0 6px 0;'>"
        f"{source['name']} &middot; {source['wua']} &middot; "
        f"{len(claims)} farms</div>"
        f"<div style='display:flex;gap:44px;align-items:flex-end;"
        f"flex-wrap:wrap;'>"
        f"{small('Deliverable water', f'{tank/1000:,.0f} kL')}"
        f"{small('Farms want', f'{demand/1000:,.0f} kL')}"
        f"<div>"
        f"<div style='font-size:{T_SMALL};color:{GREY};'>Short by</div>"
        f"<div style='font-size:56px;font-weight:700;color:{colour};"
        f"line-height:1.0;letter-spacing:-0.03em;'>{value}</div>"
        f"<div style='font-size:{T_SMALL};color:{GREY};'>{note}</div>"
        f"</div></div>", unsafe_allow_html=True)


def render_conditions(out, source_id):
    """The actual readings behind the badge. A judge should be able to
    see that 'Drought' is not a label — it is ETo 6.2 mm/day against a
    560,000 L pool, and both levers moved.

    This sits behind an expander now. The badge and its one-line summary
    carry the story; this is for the reader who wants the source."""
    w = out["weather"]
    claims = out["claims"]
    src = get_source(source_id)
    days = claims[0]["cycle_days"] if claims else CYCLE_DAYS
    eff_rain = w["rainfall_mm"] * EFFECTIVE_RAIN_FRACTION
    handed = sum(a["total_L"] for a in out["allocation"].values())

    rows = [
        ("Reference evapotranspiration (ETo)", f"{w['ETo']:.1f} mm/day",
         "How much water a standard grass field loses per day"),
        ("Rainfall", f"{w['rainfall_mm']:.0f} mm",
         f"{eff_rain:.1f} mm effective at {EFFECTIVE_RAIN_FRACTION:.0%} — "
         f"the rest runs off"),
        ("Allocation period", f"{days} days",
         "One cycle. Claims and the pool both cover this window."),
        ("Stored in the source", f"{src['live_storage_L']:,.0f} L",
         f"{src['name']} at {src['live_storage_L']/src['capacity_L']:.0%} "
         f"of capacity"),
        ("Conveyance efficiency", f"{src['conveyance_efficiency']:.0%}",
         f"{conveyance_loss_L(source_id):,.0f} L never reaches a field — "
         f"seepage and evaporation in the channel"),
        ("Water in the allocation", f"{out['tank_L']:,.0f} L",
         "Deliverable, not stored. Allocating the stored figure would "
         "promise water that never arrives."),
        ("Farms in the command area", f"{len(claims)}",
         "Every one of them was allocated, not just the twelve shown"),
        ("Allocated this cycle", f"{handed:,.0f} L",
         (f"{handed/out['tank_L']*100:.0f}% of what could be delivered — "
          f"the engine hands out everything it can" if out["tank_L"]
          else "empty source")),
    ]
    detail_table(rows)


def render_working(claims, allocation):
    """Line-by-line arithmetic for every farm. This is the 'and explains
    why' half of the pitch — a farmer told he is getting less water
    deserves a traceable reason, not a score."""
    for c in claims:
        a = allocation.get(c["farm_id"])
        if a is None:
            continue
        kc = KC[c["crop"]][c["stage"]]
        st.markdown(
            f"**{c['farm_id']} · {c['crop'].capitalize()}, "
            f"{c['stage']}** — {c['farmer_name']}")
        st.code(
            f"Kc  ({c['crop']}, {c['stage']} stage, FAO-56 Table 12) = {kc}\n"
            f"ETc = ETo x Kc                = {c['eto_used']:.1f} x {kc} "
            f"= {c['eto_used']*kc:.2f} mm/day\n"
            f"over {c['cycle_days']} days            "
            f"= {c['eto_used']*kc*c['cycle_days']:.2f} mm\n"
            f"less effective rain           - {c['effective_rain_mm']:.2f} mm\n"
            f"net depth                     "
            f"= {c['net_mm']:.2f} mm\n"
            f"x area {c['area_m2']:,} m2 (1 mm over 1 m2 = 1 L)\n"
            f"WATER REQUIRED                = {c['water_required_L']:,} L\n"
            f"\n"
            f"survival minimum = {c['water_required_L']:,} x "
            f"{c['survival_minimum_L']/max(1,c['water_required_L']):.2f} "
            f"= {c['survival_minimum_L']:,} L\n"
            f"Ky ({c['ky_stage']}, FAO-33)   = {c['ky']}\n"
            f"\n"
            f"ALLOCATED  {a['total_L']:,} L "
            f"= {a['survival_L']:,} floor + {a['surplus_L']:,} surplus\n"
            f"satisfaction = {a['total_L']:,} / {c['water_required_L']:,} "
            f"= {a['satisfaction']:.1%}\n"
            f"yield loss   = Ky x (1 - satisfaction) "
            f"= {c['ky']} x {1-a['satisfaction']:.3f} "
            f"= {c['ky']*(1-a['satisfaction'])*100:.1f}%",
            language="text")


def card_summary(claim, a):
    """The one line that has to carry the card.

    "Got 159,717 L of 288,537 L — 45% short, will lose 49% of harvest".
    Litres and percentages, no coefficients: a farmer reading this line
    alone should know whether they are in trouble."""
    need = claim["water_required_L"]
    got = a["total_L"]

    if need <= 0:
        return "Rain covered this crop — no irrigation needed this cycle"

    short_pct = (1 - a["satisfaction"]) * 100
    got_txt = f"Got <b>{got:,} L</b> of {need:,} L"
    if short_pct < 0.5:
        return f"{got_txt} — full share"
    return (f"{got_txt} — <b>{short_pct:.0f}% short</b>, will lose "
            f"{min(a['yield_loss_pct'], 100):.0f}% of harvest")


def render_card_working(claim, a):
    """What the card no longer says out loud. Every number that used to
    sit under the bar is here, plus the Ky the badge now words in
    plain language."""
    need = max(1, claim["water_required_L"])
    band, _plain, _colour = ky_band(claim["ky"])
    floor_share = claim["survival_minimum_L"] / need * 100

    detail_table([
        ("Growth stage", stage_label(claim),
         "Season stage sets Kc, growth stage sets Ky"),
        ("Water needed", f"{claim['water_required_L']:,} L",
         f"{claim['net_mm']:.2f} mm over {claim['area_m2']:,} m2"),
        ("Survival minimum", f"{claim['survival_minimum_L']:,} L",
         f"{floor_share:.0f}% of need — below this the crop dies"),
        ("Given as floor (pass 1)", f"{a['survival_L']:,} L",
         "Every farm is filled to its floor before anyone gets more"),
        ("Given as surplus (pass 2)", f"{a['surplus_L']:,} L",
         "What was left, shared by priority"),
        ("Short by",
         f"{max(0, claim['water_required_L'] - a['total_L']):,} L",
         "The gap between what was asked for and what arrived"),
        ("Sensitivity (Ky)", f"{claim['ky']:.2f}",
         f"{band} — FAO-33, {claim['ky_stage'].replace('_', ' ')} stage"),
        ("Yield loss", f"{min(a['yield_loss_pct'], 100):.0f}%",
         f"Ky x (1 - {a['satisfaction']:.2f} satisfaction)"),
    ])


def render_farm_cards(claims, allocation, limit=12):
    """One card, one sentence: what this farm grows, and what it got.

    The bar keeps the two-pass structure visible (dark = survival floor,
    light = surplus, pale = the unmet gap) and the litre-by-litre
    breakdown moved into the per-card expander. Twelve cards of seven
    numbers each is not a dashboard, it is a spreadsheet."""
    shown = claims[:limit]

    for claim in shown:
        a = allocation.get(claim["farm_id"])
        if a is None:
            st.warning(f"{claim['farm_id']} has no allocation.")
            continue

        need = max(1, claim["water_required_L"])
        floor_pct = min(100, a["survival_L"] / need * 100)
        surp_pct = min(100 - floor_pct, a["surplus_L"] / need * 100)
        gap_pct = max(0, 100 - floor_pct - surp_pct)

        band, plain_band, _band_colour = ky_band(claim["ky"])
        floor_colour, surplus_colour, _outcome = bar_colours(a)
        lost = a["total_L"] < claim["survival_minimum_L"]

        # Filled pills, in the outcome colours only. A word set in a
        # colour is easy to slide past; a pill is not.
        if lost:
            status, status_colour = "Crop lost", BAD
        elif a["contested"]:
            status, status_colour = "Contested", BAD
        else:
            status, status_colour = "Secure", OK

        # The sensitivity reads grey with everything else on this line.
        # It is a property of the crop, not an outcome, and it was
        # competing with the bar directly under it for the same glance.
        tags = [plain_band]
        if claim["is_smallholder"]:
            tags.append("Smallholder")
        if claim["fairness_debt"] > 0:
            tags.append(f"Owed from past cycles &middot; {claim['fairness_debt']:.1f}")

        # The card and its expander share one keyed container so the
        # stylesheet can space the pair as a unit — see inject_style().
        with st.container(key=f"farmcard_{claim['farm_id']}"):
            st.markdown(f"""
<div style="border:1px solid {LINE};border-left:4px solid {floor_colour};
            border-radius:3px 3px 0 0;border-bottom:none;
            padding:16px 18px 14px 18px;margin-bottom:0;
            background:{PAPER};">
  <div style="display:flex;justify-content:space-between;align-items:center;
              gap:12px;">
    <div style="font-size:{T_CARD};font-weight:600;color:{INK};
                line-height:1.3;">
      {claim['crop'].capitalize()} &middot; {growth_stage(claim)}</div>
    <div style="font-size:{T_SMALL};font-weight:700;letter-spacing:0.07em;
                text-transform:uppercase;color:{PAPER};
                background:{status_colour};padding:3px 11px;
                border-radius:999px;white-space:nowrap;">{status}</div>
  </div>

  <div style="color:{GREY};font-size:{T_SMALL};margin:5px 0 13px 0;">
    {claim['farm_id']} &middot; {claim['farmer_name']} &middot;
    {acres(claim['area_m2']):.1f} acres &middot; {' &middot; '.join(tags)}
  </div>

  <div style="display:flex;height:22px;border-radius:2px;overflow:hidden;
              background:{SHORT};">
    <div style="width:{floor_pct}%;background:{floor_colour};"></div>
    <div style="width:{surp_pct}%;background:{surplus_colour};"></div>
    <div style="width:{gap_pct}%;background:{SHORT};"></div>
  </div>

  <div style="margin-top:11px;font-size:{T_BODY};color:{INK};">
    {card_summary(claim, a)}</div>
</div>""", unsafe_allow_html=True)

            with st.expander("why this amount"):
                render_card_working(claim, a)

    if len(claims) > limit:
        st.caption(f"Showing {limit} of {len(claims)} farms. "
                   f"The engine allocated all {len(claims)}.")


def render_activity_log(log):
    """The one monospace block on the page.

    Agents were told apart by colour — four more hues competing with the
    bars for the same attention. Weight and column position do the same
    job without spending a colour: name in ink and bold, message in grey.

    The box fills its container rather than sizing to its content: the
    farm column is far longer at 12 cards than at 4, and a log that
    sizes to its own text leaves a dead rectangle beside them. Its
    container is stretched by main(), and anything past the bottom
    scrolls inside the box."""
    rows = []
    for e in log:
        rows.append(
            f"<div style='padding:3px 0;font-size:{T_SMALL};"
            f"font-family:ui-monospace,SFMono-Regular,monospace;'>"
            f"<span style='color:{GREY};'>{e['time']}</span>&nbsp;&nbsp;"
            f"<span style='color:{INK};font-weight:700;display:inline-block;"
            f"min-width:88px;'>{e['agent']}</span>"
            f"&nbsp;<span style='color:{GREY};'>{e['message']}</span></div>")
    st.markdown(
        f"<div style='background:{PAPER};border:1px solid {LINE};"
        f"border-radius:3px;padding:12px 16px;height:100%;min-height:260px;"
        f"box-sizing:border-box;overflow:auto;'>"
        f"{''.join(rows)}</div>",
        unsafe_allow_html=True)


def render_impact(scorecard):
    h = scorecard["headline"]
    has_small = h.get("has_smallholders", True)

    # The two columns were set at equal weight, which reads as a
    # neutral comparison. It is not one — the right-hand column is the
    # claim being made, so it carries a tint and heavier figures, and
    # the crops-lost row is set large because that row is the argument.
    small_row = (
        f"""  <tr>
    <td style="padding:9px 6px;color:{GREY};">Smallholder harvest kept</td>
    <td style="text-align:right;padding:9px 6px;color:{GREY};">
        {h['yieldmax_smallholder_kept_pct']:.0f}%</td>
    <td style="text-align:right;padding:9px 10px;font-weight:700;
               color:{INK};background:{TINT};">
        {h['aquafair_smallholder_kept_pct']:.0f}%</td>
  </tr>""" if has_small else
        f"""  <tr>
    <td style="padding:9px 6px;color:{GREY};">Smallholder harvest kept</td>
    <td colspan="2" style="text-align:right;padding:9px 10px;color:{GREY};
        font-size:{T_SMALL};">no holdings under 2 ha in this command area</td>
  </tr>""")

    st.markdown(f"""
<table style="width:100%;border-collapse:collapse;font-size:{T_BODY};">
  <tr style="border-bottom:2px solid {INK};">
    <th style="text-align:left;padding:8px 6px;"></th>
    <th style="text-align:right;padding:8px 6px;color:{GREY};
               font-size:{T_SMALL};font-weight:600;">Maximise yield</th>
    <th style="text-align:right;padding:8px 10px;color:{INK};
               font-size:{T_SMALL};font-weight:700;background:{TINT};">
        AquaFair</th>
  </tr>
  <tr style="border-bottom:1px solid {LINE};">
    <td style="padding:9px 6px;color:{GREY};">Total food produced</td>
    <td style="text-align:right;padding:9px 6px;color:{GREY};">
        {h['yieldmax_food_kg']:,} kg</td>
    <td style="text-align:right;padding:9px 10px;font-weight:700;
               color:{INK};background:{TINT};">
        {h['aquafair_food_kg']:,} kg</td>
  </tr>
  <tr style="border-bottom:1px solid {LINE};">
    <td style="padding:9px 6px;color:{GREY};">Staple food produced</td>
    <td style="text-align:right;padding:9px 6px;color:{GREY};">
        {h['yieldmax_staple_kg']:,} kg</td>
    <td style="text-align:right;padding:9px 10px;font-weight:700;
               color:{INK};background:{TINT};">
        {h['aquafair_staple_kg']:,} kg</td>
  </tr>
  <tr style="border-bottom:1px solid {LINE};">
    <td style="padding:13px 6px;color:{INK};font-weight:600;">
        Crops lost entirely</td>
    <td style="text-align:right;padding:13px 6px;color:{BAD};
               font-weight:700;font-size:{T_HEAD};">
        {h['yieldmax_crops_lost']}</td>
    <td style="text-align:right;padding:13px 10px;color:{OK};
               font-weight:700;font-size:{T_HEAD};background:{TINT};">
        {h['aquafair_crops_lost']}</td>
  </tr>
{small_row}
</table>""", unsafe_allow_html=True)

    # ⚠ "More food" is NOT universal — it depends on the crop mix.
    # Sugarcane yields 7 kg/m2 against ragi's 0.25, so on a canal command
    # area growing cane, 85% of total tonnage is sugarcane and a policy
    # that feeds the cane and starves everything else wins on kilograms.
    # The claim that holds on every source is "loses no crops". Say that
    # one out loud; let this line appear only when it is actually true.
    if h["food_gain_kg"] > 0:
        st.markdown(
            f"<p style='margin-top:12px;color:{INK};font-size:{T_BODY};'>"
            f"AquaFair produces <b>{h['food_gain_kg']:,} kg more food</b> "
            f"({h['food_gain_pct']:+.1f}%) while losing no crops. A dead crop "
            f"wastes a whole season of water.</p>", unsafe_allow_html=True)
    else:
        staple_gain = h["aquafair_staple_kg"] - h["yieldmax_staple_kg"]
        extra = (f" and <b>{staple_gain:,} kg more staple food</b>"
                 if staple_gain > 0 else "")
        st.markdown(
            f"<p style='margin-top:12px;color:{INK};font-size:{T_BODY};'>"
            f"Maximising yield produces more raw tonnage here — most of it "
            f"from a few high-yield cash crops — but it loses "
            f"<b>{h['yieldmax_crops_lost']} crops entirely</b>. AquaFair "
            f"loses none{extra}.</p>", unsafe_allow_html=True)

    with st.expander("All four policies, side by side"):
        st.dataframe(
            {
                "Policy": ["Maximise yield", "Equal split", "Emergency", "AquaFair"],
                "Food (kg)": [scorecard[k]["total_yield_kg"]
                              for k in ("yield_max", "naive", "emergency", "equity")],
                "Staple (kg)": [scorecard[k]["staple_yield_kg"]
                                for k in ("yield_max", "naive", "emergency", "equity")],
                "Crops lost": [scorecard[k]["crops_lost"]
                               for k in ("yield_max", "naive", "emergency", "equity")],
                "Smallholder kept": [f"{scorecard[k]['smallholder_kept_pct']:.0f}%"
                                     if scorecard[k].get("has_smallholders", True)
                                     else "—"
                                     for k in ("yield_max", "naive", "emergency", "equity")],
                "Water used (L)": [scorecard[k]["water_used_L"]
                                   for k in ("yield_max", "naive", "emergency", "equity")],
            },
            hide_index=True, width='stretch')


# ═════════════════════════════════════════════════════════════════
# THE AGENT TRACE
#
# This is what gets opened when a judge asks whether any of it is
# hardcoded. Every figure is read back out of the live run: the claims
# the farm agents built, the round records the coordinator kept, the
# scorecard impact.py computed. If a number here is wrong, the number on
# the dashboard is wrong too — they are the same number.
#
# Two pure functions from the engine are called for display only
# (compute_actual_yield, and the priority factors re-multiplied against
# the score the optimizer already stored). Neither runs the pipeline
# again, so the rule at the top of this file still holds: compute() is
# the only place that ALLOCATES.
#
# ⚠ Agents 2 and 3 need coordination["rounds"] — a per-round record of
# urgency, allocations, contests and escalations. If coordinator.py does
# not keep one, those panels say so plainly rather than printing an
# empty table that looks like the engine did nothing.
#
# Monospace, fixed columns, lines under ~88 characters — it has to be
# readable aloud from a projector.
# ═════════════════════════════════════════════════════════════════

TRACE_WORKED_EXAMPLES = 2    # farms whose full arithmetic is spelled out
TRACE_TABLE_ROWS      = 12   # farms listed in the per-agent tables

NO_ROUNDS_NOTE = (
    "  coordinator.py is not recording per-round detail, so the round-by-\n"
    "  round view is unavailable. The allocation above is real; only this\n"
    "  breakdown is missing. Add a `rounds` list to run_coordination()'s\n"
    "  return to switch it on.")


def _eq(label, value, indent=2):
    """'  label ............ = value' — one aligned equation line.

    The space before the "=" is not decoration: a label longer than the
    pad would otherwise print "...x 44,146= 25,345 L", which reads as a
    typo in the one panel that exists to look trustworthy."""
    return f"{' ' * indent}{label:<41} = {value}"


def _more(total, shown, what):
    """Never let a table imply it covered everything when it did not."""
    if total <= shown:
        return []
    return ["", f"  ... {total - shown} more {what} not listed here "
                f"(all {total} were allocated)."]


def _wrap(text, width):
    """Tiny greedy wrapper — textwrap would do, but this keeps the trace
    dependency-free and the behaviour obvious."""
    words, line, out = text.split(), "", []
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


def trace_agent_1(out):
    """AGENT 1 — farm intelligence, one instance per farm."""
    claims = out["claims"]
    w = out["weather"]
    L = [
        f"{len(claims)} instance(s), one per farm. Each one reads its own crop,",
        "stage and area, then asks the shared weather for ETo and rainfall.",
        f"This cycle: ETo {w['ETo']:.1f} mm/day, rainfall {w['rainfall_mm']:.0f} mm "
        f"({claims[0]['effective_rain_mm']:.2f} mm effective),",
        f"allocation period {claims[0]['cycle_days']} days.",
        "",
        f"{'FARM':<6}{'CROP':<9}{'STAGE':<13}{'Kc':>5}{'ETo':>6}"
        f"{'NEED L':>11}{'FLOOR L':>10}{'FLOOR':>7}{'Ky':>6}",
    ]
    for c in claims[:TRACE_TABLE_ROWS]:
        floor_pct = c["survival_minimum_L"] / max(1, c["water_required_L"]) * 100
        L.append(
            f"{c['farm_id']:<6}{c['crop']:<9}{c['stage']:<13}"
            f"{c['kc']:>5.2f}{c['eto_used']:>6.1f}"
            f"{c['water_required_L']:>11,}{c['survival_minimum_L']:>10,}"
            f"{floor_pct:>6.0f}%{c['ky']:>6.2f}")
    L += _more(len(claims), TRACE_TABLE_ROWS, "farm(s)")

    # The arithmetic, spelled out, for the biggest requirements.
    biggest = sorted(claims, key=lambda c: -c["water_required_L"])
    for c in biggest[:TRACE_WORKED_EXAMPLES]:
        etc = c["eto_used"] * c["kc"]
        gross = etc * c["cycle_days"]
        floor_pct = c["survival_minimum_L"] / max(1, c["water_required_L"]) * 100
        L += [
            "",
            f"{c['farm_id']} {c['crop'].capitalize()}, {c['stage']} stage "
            f"({c['ky_stage'].replace('_', ' ')}), {c['farmer_name']}:",
            _eq(f"ETo {c['eto_used']:.1f} x Kc {c['kc']:.2f}  (FAO-56 Table 12)",
                f"{etc:.2f} mm/day"),
            _eq(f"x {c['cycle_days']} days", f"{gross:.2f} mm"),
            _eq(f"less effective rain {c['effective_rain_mm']:.2f} mm",
                f"{c['net_mm']:.2f} mm net"),
            _eq(f"x {c['area_m2']:,} m2  (1 mm over 1 m2 = 1 L)",
                f"{c['water_required_L']:,} L required"),
            _eq(f"survival floor, {floor_pct:.0f}% of requirement",
                f"{c['survival_minimum_L']:,} L"),
            _eq(f"Ky at {c['ky_stage'].replace('_', ' ')}  (FAO-33)",
                f"{c['ky']:.2f}"),
        ]
    if len(claims) > TRACE_WORKED_EXAMPLES:
        L += ["", f"  The other {len(claims) - TRACE_WORKED_EXAMPLES} farm(s) "
                  f"follow the same six lines — open",
              "  'Show the working for every farm' below the Impact panel."]
    return "\n".join(L)


def trace_agent_2(out):
    """AGENT 2 — the optimizer's two passes."""
    claims = out["claims"]
    alloc = out["allocation"]
    rounds = out["coordination"].get("rounds", [])
    pool = out["tank_L"]

    total_survival = sum(c["survival_minimum_L"] for c in claims)
    committed = sum(a["survival_L"] for a in alloc.values())
    surplus_paid = sum(a["surplus_L"] for a in alloc.values())
    feasible = total_survival <= pool

    L = ["PASS 1 — every survival floor is paid before anyone gets more", ""]
    L += [
        _eq(f"total survival need across {len(claims)} farms",
            f"{total_survival:,.0f} L"),
        _eq("deliverable water in the pool", f"{pool:,.0f} L"),
    ]
    if feasible:
        L += [
            f"  {total_survival:,.0f} <= {pool:,.0f}, so every floor is paid "
            f"in full.",
            _eq("committed in pass 1", f"{committed:,} L"),
            _eq("left for pass 2", f"{pool - committed:,.0f} L"),
        ]
    else:
        L += [
            f"  {total_survival:,.0f} > {pool:,.0f}, so no floor can be paid "
            f"in full. Pass 1",
            "  splits the pool proportional to (survival minimum x urgency),",
            "  and there is nothing left for pass 2.",
            _eq("committed in pass 1", f"{committed:,} L"),
            _eq("left for pass 2", "0 L"),
        ]

    L += ["", "PASS 2 — the surplus, shared by priority score", "",
          "  score = Ky x food weight x shortage gap x smallholder boost",
          "          x (1 + fairness debt) x urgency",
          "",
          f"  Shortage gap is (requirement - floor). Smallholder boost is "
          f"{SMALLHOLDER_BOOST}x.",
          "  Expected yield is deliberately NOT a factor: scoring by absolute",
          "  tonnage hands every surplus to whoever is already largest, and",
          "  the gap widens every cycle. See the note in optimizer.py.",
          ""]

    urgency = rounds[-1]["urgency"] if rounds else {}
    if not rounds:
        L += ["  (urgency column shows 1.00 — see the note under AGENT 3)", ""]

    L.append(f"{'FARM':<6}{'Ky':>5}{'FOOD':>6}{'GAP L':>11}{'SMALL':>7}"
             f"{'DEBT':>7}{'URGENT':>8}{'SCORE':>13}{'SURPLUS L':>12}")
    scored = []
    for c in claims[:TRACE_TABLE_ROWS]:
        fid = c["farm_id"]
        a = alloc[fid]
        gap = max(0, c["water_required_L"] - c["survival_minimum_L"])
        boost = SMALLHOLDER_BOOST if c["is_smallholder"] else 1.0
        u = urgency.get(fid, 1.0)
        L.append(
            f"{fid:<6}{c['ky']:>5.2f}{c['food_weight']:>6.2f}{gap:>11,}"
            f"{boost:>7.2f}{1 + c['fairness_debt']:>7.2f}{u:>8.2f}"
            f"{a['priority_score']:>13,.0f}{a['surplus_L']:>12,}")
        scored.append((fid, a["priority_score"], a["surplus_L"]))
    L += _more(len(claims), TRACE_TABLE_ROWS, "farm(s)")

    total_score = sum(a["priority_score"] for a in alloc.values())
    L += ["", _eq("total score across every farm", f"{total_score:,.0f}")]

    if scored and total_score > 0 and surplus_paid > 0:
        fid, score, got = max(scored, key=lambda t: t[1])
        raw = score / total_score * surplus_paid
        L += [
            _eq(f"{fid} raw share = {score:,.0f} / {total_score:,.0f} "
                f"x {surplus_paid:,.0f}", f"{raw:,.0f} L"),
            _eq(f"{fid} surplus actually paid", f"{got:,} L"),
        ]
        if abs(raw - got) > 1:
            L += ["  The two differ because a farm that reaches its full",
                  "  requirement is capped there and the remainder is recycled",
                  "  to the others — optimizer._share_out loops until the pool",
                  "  is empty or every gap is closed."]
    L += ["", _eq("surplus paid out in pass 2", f"{surplus_paid:,} L"),
          _eq("total handed to farms", f"{committed + surplus_paid:,} L"),
          _eq("of a deliverable pool of", f"{pool:,.0f} L")]
    return "\n".join(L)


def trace_agent_3(out):
    """AGENT 3 — the negotiation, round by round."""
    co = out["coordination"]
    rounds = co.get("rounds", [])
    L = [
        f"A farm contests if it is below its survival minimum, OR its",
        f"projected yield loss is above {CONTEST_YIELD_LOSS_PCT:.0f}% "
        f"(CONTEST_YIELD_LOSS_PCT).",
        f"Each contest multiplies that farm's urgency by "
        f"{ESCALATION_FACTOR}x (ESCALATION_FACTOR)",
        f"and the optimizer re-runs. At most {MAX_ROUNDS} rounds "
        f"(MAX_ROUNDS).",
        "",
        _eq("rounds this allocation actually used",
            f"{co['rounds_used']} of {MAX_ROUNDS}"),
        _eq("every farm reached its survival floor",
            "yes" if co["all_survival_met"] else "no"),
    ]
    contested_now = [f for f, a in out["allocation"].items() if a["contested"]]
    L.append(_eq("farms that contested at any point",
                 ", ".join(contested_now) if contested_now else "none"))

    if not rounds:
        L += ["", NO_ROUNDS_NOTE]
        return "\n".join(L)

    for i, r in enumerate(rounds):
        urg = r["urgency"]
        moved = [f"{f} {u:.2f}x" for f, u in urg.items() if u > 1.0]
        head = ", ".join(moved) if moved else "every farm at 1.00x"
        L += ["", f"ROUND {r['round']}  {head}",
              f"  {r['handed_out_L']:,.0f} L allocated across "
              f"{len(r['given'])} farms."]

        if i > 0:
            prev = rounds[i - 1]["given"]
            deltas = [(f, g - prev.get(f, 0)) for f, g in r["given"].items()]
            deltas = sorted([d for d in deltas if abs(d[1]) >= 1],
                            key=lambda d: -abs(d[1]))
            if deltas:
                shown = ", ".join(f"{f} {d:+,} L" for f, d in deltas[:5])
                tail = f" (+{len(deltas) - 5} more)" if len(deltas) > 5 else ""
                L.append(f"  moved vs round {rounds[i-1]['round']}: {shown}{tail}")
            else:
                L.append(f"  nothing moved vs round {rounds[i-1]['round']}.")

        for c in r["contested"][:TRACE_TABLE_ROWS]:
            why = (f"below survival, {c['allocated_L']:,} L of "
                   f"{c['survival_L']:,} L" if c["below_survival"]
                   else f"facing {c['yield_loss_pct']:.0f}% yield loss")
            L.append(f"  {c['farm_id']} {c['crop']:<9} {why:<44} CONTEST")
        if len(r["contested"]) > TRACE_TABLE_ROWS:
            L.append(f"  ... {len(r['contested']) - TRACE_TABLE_ROWS} more "
                     f"contesting farm(s) not listed.")
        if not r["contested"]:
            L.append("  no farm contested.")

        if r["escalated"]:
            esc = ", ".join(f"{f} -> {m:.2f}x"
                            for f, m in list(r["escalated"].items())[:6])
            more = (f" (+{len(r['escalated']) - 6} more)"
                    if len(r["escalated"]) > 6 else "")
            L.append(f"  escalated: {esc}{more}")

    last = rounds[-1]
    L += ["", f"OUTCOME — {last['outcome'].upper()} after "
              f"{co['rounds_used']} round(s)"]
    for chunk in _wrap(last["note"], 84):
        L.append(f"  {chunk}")
    return "\n".join(L)


def trace_agent_4(out):
    """AGENT 4 — impact, against the baselines."""
    sc = out["scorecard"]
    h = sc["headline"]
    claims = out["claims"]
    alloc = out["allocation"]

    L = [
        "BASELINE — naive equal split",
        "  The pool divided equally across farms. Water a farm cannot use is",
        "  recycled to the others in further equal rounds, so this is the",
        "  strong version of the baseline, not a strawman that wastes water.",
        "",
        f"{'POLICY':<20}{'FOOD kg':>10}{'STAPLE kg':>11}{'LOST':>6}"
        f"{'SMALL KEPT':>12}{'WATER L':>12}",
    ]
    names = [("yield_max", "maximise yield"), ("naive", "equal split"),
             ("emergency", "emergency split"), ("equity", "AquaFair")]
    for key, label in names:
        row = sc[key]
        small = (f"{row['smallholder_kept_pct']:>11.1f}%"
                 if row.get("has_smallholders", True) else f"{'—':>12}")
        L.append(
            f"{label:<20}{row['total_yield_kg']:>10,}"
            f"{row['staple_yield_kg']:>11,}{row['crops_lost']:>6}"
            f"{small}{row['water_used_L']:>12,}")

    L += ["", "HEADLINE — AquaFair against pure yield maximisation", ""]
    L += [
        _eq(f"food gain = {h['aquafair_food_kg']:,} - "
            f"{h['yieldmax_food_kg']:,}", f"{h['food_gain_kg']:,} kg"),
        _eq(f"as a percentage of {h['yieldmax_food_kg']:,} kg",
            f"{h['food_gain_pct']:+.1f}%"),
        _eq("staple food (food weight >= 1.0)",
            f"yield_max {h['yieldmax_staple_kg']:,} kg, "
            f"AquaFair {h['aquafair_staple_kg']:,} kg"),
        _eq("crops lost (farms under their floor)",
            f"yield_max {h['yieldmax_crops_lost']}, "
            f"AquaFair {h['aquafair_crops_lost']}"),
    ]
    if h.get("has_smallholders", True):
        L += [
            _eq("smallholder harvest kept",
                f"yield_max {h['yieldmax_smallholder_kept_pct']:.0f}%, "
                f"AquaFair {h['aquafair_smallholder_kept_pct']:.0f}%"),
            _eq("smallholder kg kept of potential",
                f"{sc['equity']['smallholder_yield_kg']:,} of "
                f"{sc['equity']['smallholder_potential_kg']:,} kg"),
        ]
    else:
        L += [_eq("smallholder harvest kept",
                  "no holdings under 2 ha here")]

    if h["food_gain_kg"] <= 0:
        L += ["",
              "  Note: raw tonnage favours yield_max in this command area.",
              "  Sugarcane yields 7 kg/m2 against ragi's 0.25, so feeding the",
              "  cane and starving everything else wins on kilograms while",
              "  losing whole crops. The claim that holds on every source is",
              "  'loses no crops' — read the LOST column, not FOOD kg."]

    L += ["", "YIELD ARITHMETIC — how one farm's kg is worked out", "",
          "  loss   = Ky x (1 - allocated / required), clamped to 0-1",
          "  yield  = expected kg x (1 - loss)",
          "  below the survival floor, yield tapers linearly to zero",
          "  instead of stepping off a cliff at the floor.",
          ""]
    worked = sorted(claims, key=lambda c: -c["expected_yield_kg"])[:1]
    for c in worked:
        a = alloc[c["farm_id"]]
        got, need = a["total_L"], max(1, c["water_required_L"])
        kg = compute_actual_yield(c, got)
        L += [f"{c['farm_id']} {c['crop'].capitalize()}, {c['farmer_name']}:"]
        if got >= c["survival_minimum_L"]:
            loss = min(1.0, max(0.0, c["ky"] * (1 - got / need)))
            L += [
                _eq(f"got {got:,} L of {need:,} L", f"{got/need:.1%} satisfied"),
                _eq(f"loss = Ky {c['ky']:.2f} x (1 - {got/need:.3f})",
                    f"{loss:.3f}"),
                _eq(f"yield = {c['expected_yield_kg']:,} kg x (1 - {loss:.3f})",
                    f"{kg:,} kg"),
            ]
        else:
            L += [
                _eq(f"got {got:,} L, below its floor of "
                    f"{c['survival_minimum_L']:,} L", "crop lost"),
                _eq("yield tapers linearly from the floor to zero",
                    f"{kg:,} kg"),
            ]
    L += ["", _eq("every policy column above uses the same pool",
                  f"{out['tank_L']:,.0f} L")]
    return "\n".join(L)


def render_agent_trace(out, source):
    """The four agents, in the order the pipeline runs them."""
    st.caption(
        f"Live trace of the allocation currently on screen — "
        f"{source['name']}, {len(out['claims'])} farms, "
        f"{out['tank_L']:,.0f} L deliverable, "
        f"ETo {out['weather']['ETo']:.1f} mm/day, "
        f"{out['coordination']['rounds_used']} negotiation round(s). "
        f"Change any reading and every number here changes with it.")

    for title, body in (
            ("AGENT 1 — FARM INTELLIGENCE", trace_agent_1(out)),
            ("AGENT 2 — RESOURCE OPTIMIZER", trace_agent_2(out)),
            ("AGENT 3 — COORDINATION", trace_agent_3(out)),
            ("AGENT 4 — IMPACT", trace_agent_4(out))):
        st.markdown(
            f"<div style='font-family:ui-monospace,SFMono-Regular,monospace;"
            f"font-size:0.9rem;font-weight:700;color:{INK};"
            f"letter-spacing:0.04em;margin:14px 0 2px 0;'>{title}</div>",
            unsafe_allow_html=True)
        st.code(body, language="text")


@st.dialog("How the four agents worked", width="large")
def agent_trace_dialog(out, source):
    render_agent_trace(out, source)


# ══════════════════════════════════════════════════════════════════
# STATE
# ══════════════════════════════════════════════════════════════════

def init_state():
    ss = st.session_state
    ss.setdefault("farms", demo_farms())
    ss.setdefault("mode", "equity")                # equity, never yield_max
    ss.setdefault("scale_tank", False)             # sources are real volumes
    ss.setdefault("source_id", DEFAULT_SOURCE)
    # The readings ARE the state. There is no "current scenario" to fall
    # out of step with them — a preset button just writes two of these
    # numbers and the whole dashboard follows.
    for k, v in WEATHER_STATES[DEFAULT_WEATHER].items():
        ss.setdefault(f"w_{k}", float(v))
    # Open on the default source's deliverable water, not the preset's
    # tank figure — otherwise the first screen shows a volume that
    # belongs to no command area.
    ss.setdefault("_water_seeded", False)
    if not ss._water_seeded:
        ss.w_tank_liters = float(deliverable_water_L(ss.source_id))
        ss._water_seeded = True
    ss.setdefault("notice", None)
    # Change detection ONLY. Nothing on screen reads these — the badge is
    # classified fresh from the readings on every rerun. This is here so
    # the Weather agent can say what moved since the last one.
    ss.setdefault("last_seen", None)     # (label, ETo, rain, shortfall)


def load_preset(key):
    """Write a preset's WEATHER readings into state — and nothing else.

    A preset is a shortcut for typing numbers, not a mode. It must never
    set the condition label: the label is classified from the readings,
    so typing 6.2 by hand and pressing Drought have to reach the same
    word by the same route.

    ⚠ TANK LEVEL IS DELIBERATELY NOT TOUCHED. The preset tank figures in
    constants.py were sized for the 4-farm demo; the real volume for the
    command area on screen comes from sources.py. A preset that
    overwrote it would silently swap a gauge reading for a demo number —
    press Drought on the 72 ha canal and its 9.6 million litres would
    become 480,000.

    ⚠ This MUST be an on_click callback, not inline button-handling
    code. Streamlit raises StreamlitAPIException if you assign to
    st.session_state["w_ETo"] after the number_input bound to that key
    has already rendered — which is exactly what inline handling does,
    because the buttons sit below the inputs. Callbacks run BEFORE the
    next script run, so the widgets pick the new values up cleanly.
    """
    preset = WEATHER_STATES[key]
    st.session_state.w_ETo = float(preset["ETo"])
    st.session_state.w_rainfall_mm = float(preset["rainfall_mm"])


def load_source_water():
    """Put the selected source's DELIVERABLE water into the pool field.

    Deliverable, not stored. An unlined channel loses a third of a
    release to seepage before it reaches a field, so allocating the
    stored figure would promise farmers water that never arrives.
    """
    st.session_state.w_tank_liters = float(
        deliverable_water_L(st.session_state.source_id))


def note_condition_change(label, eto, rainfall_mm, shortfall):
    """Log a line from the Weather agent when the classification moves.

    The label is not kept as state anyone renders from — it is held for
    exactly one rerun so the next one can name what changed. The first
    run records a baseline silently; there is nothing to compare against
    yet.

    Returns the entry for the rerun that changed, or None. It is not
    kept: the log shows this run and nothing else, so clicking through
    the presets leaves no trail behind on screen.

    All three classifier inputs go in the message. Dropping the shortfall
    would produce lines like "(ETo 6.2->6.2, rain 0->0mm)" whenever the
    water level is what moved — a reclassification with nothing visibly
    behind it, which is the opposite of the point."""
    ss = st.session_state
    previous = ss.last_seen
    ss.last_seen = (label, eto, rainfall_mm, shortfall)

    if previous is None or previous[0] == label:
        return None

    was, was_eto, was_rain, was_short = previous
    return {
        "time": datetime.now().strftime("%H:%M:%S"),
        "agent": "Weather",
        "message": (f"Conditions reclassified: {was} → {label} "
                    f"(ETo {was_eto:.1f}→{eto:.1f}, "
                    f"rain {was_rain:.0f}→{rainfall_mm:.0f}mm, "
                    f"shortfall {was_short:.0f}→{shortfall:.0f}%)"),
    }


def next_farm_id():
    used = {f["farm_id"] for f in st.session_state.farms}
    i = 1
    while f"F{i:03d}" in used:
        i += 1
    return f"F{i:03d}"


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

def main():
    st.set_page_config(page_title="AquaFair", layout="wide",
                       initial_sidebar_state="expanded")
    init_state()
    inject_style()
    ss = st.session_state

    st.markdown(f"""
<div style="border-bottom:2px solid {INK};padding-bottom:12px;margin-bottom:20px;">
  <div style="font-size:{T_TITLE};font-weight:700;color:{INK};
              letter-spacing:-0.02em;line-height:1.2;">
    AquaFair</div>
  <div style="color:{GREY};font-size:{T_BODY};margin-top:2px;">
    There is less water than the farms want. This decides who gets what,
    and explains why.</div>
</div>""", unsafe_allow_html=True)

    # ---------------- sidebar controls ----------------
    with st.sidebar:
        section("Command area")
        st.selectbox(
            "Tank or canal", list_sources(), key="source_id",
            format_func=lambda s: f"{get_source(s)['name']}  ({s})",
            on_change=load_source_water,
            help="Each source serves its own farms and its own WUA. "
                 "Tank A never gives water to Tank B's farms.")
        _t = get_source(ss.source_id)
        _usable = deliverable_water_L(ss.source_id)
        _served = len(farms_for_source(ss.farms, ss.source_id))
        st.markdown(
            f"<div style='font-size:{T_SMALL};color:{GREY};line-height:1.75;"
            f"border-left:2px solid {LINE};padding-left:10px;"
            f"margin:4px 0 14px;'>"
            f"{_t['wua']}<br>"
            f"Command area <b style='color:{INK};'>{_t['command_area_ha']} ha"
            f"</b> &middot; <b style='color:{INK};'>{_served}</b> farms<br>"
            f"Stored <b style='color:{INK};'>{_t['live_storage_L']:,.0f}</b> L "
            f"of {_t['capacity_L']:,.0f} L "
            f"({_t['live_storage_L']/_t['capacity_L']:.0%} full)<br>"
            f"Conveyance <b style='color:{INK};'>"
            f"{_t['conveyance_efficiency']:.0%}</b> &rarr; deliverable "
            f"<b style='color:{INK};'>{_usable:,.0f}</b> L<br>"
            f"<span style='color:{BAD};'>Lost in transit "
            f"{conveyance_loss_L(ss.source_id):,.0f} L</span></div>",
            unsafe_allow_html=True)

        section("Conditions")
        st.caption("This week's readings. Everything below is computed "
                   "from these three numbers.")

        # Widgets are bound to session_state by key. Streamlit ignores
        # `value=` once a key exists, so binding directly is the only way
        # a preset button can change what the boxes show. Passing both is
        # how the boxes and the panel ended up disagreeing.
        st.number_input(
            "Reference evapotranspiration (mm/day)",
            0.0, 15.0, step=0.1, key="w_ETo",
            help="How much water a standard grass field loses per day. "
                 "Tamil Nadu runs roughly 4-7 depending on season.")
        st.number_input(
            "Rainfall this cycle (mm)",
            0.0, 500.0, step=1.0, key="w_rainfall_mm",
            help=f"Only {EFFECTIVE_RAIN_FRACTION:.0%} reaches the root "
                 f"zone; the rest runs off or drains below it.")
        st.number_input(
            "Water for this allocation (litres)",
            0.0, 1e9, step=10_000.0, key="w_tank_liters",
            help="Deliverable water, seeded from the selected source. "
                 "In deployment this is a gauge reading less conveyance "
                 "loss, not a setting.")

        st.markdown(
            f"<div style='font-size:{T_SMALL};color:{GREY};"
            f"border-left:2px solid {LINE};padding-left:9px;"
            f"margin:2px 0 10px 0;'>"
            f"Effective rain <b style='color:{INK};'>"
            f"{ss.w_rainfall_mm * EFFECTIVE_RAIN_FRACTION:.1f}</b> mm "
            f"of {ss.w_rainfall_mm:.0f} mm</div>", unsafe_allow_html=True)

        # Presets are a shortcut for typing, not a mode. They write ETo
        # and rainfall, and stop there: the badge above is classified
        # from those numbers, so a preset cannot claim a condition the
        # readings do not support. Buttons, not a radio, for the same
        # reason — a radio would still be lit on "Heavy rain" after you
        # edited the numbers under it.
        # One per row: three across a sidebar column broke the labels
        # mid-word ("Norma l", "Droug ht"). Full width fits them whole.
        #
        # The description is printed under each button, not passed as
        # `help`. Streamlit floats a button tooltip ABOVE the button,
        # where it covered the caption above on hover. Text that is
        # always visible cannot collide with anything, and a judge
        # reading the sidebar aloud gets it for free.
        st.caption("Or load known weather readings:")
        for key, (label, note) in SCENARIOS.items():
            st.button(label, key=f"preset_{key}", width='stretch',
                      on_click=load_preset, args=(key,))
            st.markdown(
                f"<div style='font-size:{T_SMALL};color:{GREY};"
                f"margin:-6px 0 8px 0;text-align:center;'>{note}</div>",
                unsafe_allow_html=True)

        st.checkbox(
            "Scale water with farm count", key="scale_tank",
            help="Off by default: the figure above is a real volume for "
                 "this command area. Turn it on only when using a demo "
                 "preset volume with a farm count it was not sized for.")

        st.divider()
        section("Farms")
        st.caption(f"{_served} under this source, "
                   f"{len(ss.farms)} in the district")

        b1, b2 = st.columns(2)
        if b1.button("Demo set", width='stretch'):
            ss.farms = demo_farms()
            ss.notice = None
            st.rerun()
        if b2.button("Load 100", width='stretch'):
            ss.farms = generate_farms(100, seed=42)
            ss.notice = None
            st.rerun()

        with st.expander("Add a farm"):
            with st.form("add_farm", clear_on_submit=True):
                st.caption(f"Joins {get_source(ss.source_id)['name']}.")
                name = st.text_input("Farmer's name")
                crop = st.selectbox("Crop", sorted(KC),
                                    format_func=str.capitalize)
                stage = st.selectbox("Growth stage", STAGES,
                                     format_func=lambda s: s.capitalize())
                area_ac = st.number_input("Area (acres)", 0.1, 100.0, 2.0, 0.1)
                debt = st.slider("Owed from past cycles", 0.0, 2.0, 0.0, 0.1,
                                 help="Raises priority. A farm short-changed "
                                      "last cycle ranks higher now.")
                if st.form_submit_button("Add farm", width='stretch'):
                    clean = name.strip()
                    if not clean:
                        ss.notice = ("error", "Enter a farmer's name.")
                    else:
                        from constants import TYPICAL_YIELD_KG_PER_M2
                        area_m2 = round(area_ac * M2_PER_ACRE)
                        ss.farms.append({
                            "farm_id": next_farm_id(),
                            "source_id": ss.source_id,
                            "farmer_name": clean,
                            "crop": crop,
                            "stage": stage,
                            "area_m2": area_m2,
                            "soil_moisture_pct": 35.0,
                            "expected_yield_kg": max(
                                1, round(area_m2 * TYPICAL_YIELD_KG_PER_M2[crop])),
                            "is_smallholder": area_m2 < SMALLHOLDER_AREA_M2,
                            "fairness_debt": round(debt, 2),
                        })
                        ss.notice = ("success",
                                     f"Added {clean}'s {crop} under "
                                     f"{get_source(ss.source_id)['name']}. "
                                     f"Everything below recomputed.")
                    st.rerun()

    # ---------------- compute once, render from it ----------------
    if ss.notice:
        kind, msg = ss.notice
        (st.success if kind == "success" else st.error)(msg)
        ss.notice = None

    # ONE command area. Filtered before compute() is called, so the
    # engine is never even shown another source's farms.
    served = farms_for_source(ss.farms, ss.source_id)
    source = get_source(ss.source_id)
    if not served:
        st.info(f"No farms registered under {source['name']}. Add one, "
                f"load the demo set, or pick another command area.")
        return

    weather = {"ETo": ss.w_ETo,
               "rainfall_mm": ss.w_rainfall_mm,
               "tank_liters": ss.w_tank_liters}
    out = compute(served, weather, ss.mode, scale_tank=ss.scale_tank)

    if "error" in out:
        st.error(f"The engine could not complete this allocation: {out['error']}")
        return

    out["mode"] = ss.mode
    render_top_bar(out, source)

    # Classified here, every rerun, from the readings and the shortfall
    # the engine just produced. Nothing carries a label forward.
    shortfall = shortfall_pct(out)
    condition, condition_colour, condition_why = classify_conditions(
        ss.w_ETo, ss.w_rainfall_mm, shortfall)
    weather_line = note_condition_change(
        condition, ss.w_ETo, ss.w_rainfall_mm, shortfall)
    render_condition_badge(condition, condition_colour, condition_why)
    st.write("")

    if out["coordination"].get("supply_infeasible", False):
        st.error("Supply is below the total survival minimum. Every farm is "
                 "under its floor. No reallocation can fix a shortfall this "
                 "size — only more water.")

    left, right = st.columns([3, 2], gap="large")

    with left:
        with st.expander("This week's readings"):
            render_conditions(out, ss.source_id)
        st.write("")

        section("Farms")
        st.caption("Every farm is brought up to its survival minimum "
                   "first. Whatever is left over is shared by priority.")
        st.markdown(
            f"<div style='font-size:{T_SMALL};color:{GREY};"
            f"margin:-4px 0 12px 0;'>"
            f"<span style='color:{OK};'>&#9632;</span> full share"
            f"&nbsp;&nbsp;<span style='color:{WARN};'>&#9632;</span> "
            f"partly short&nbsp;&nbsp;"
            f"<span style='color:{BAD};'>&#9632;</span> badly short "
            f"or contested</div>", unsafe_allow_html=True)
        render_farm_cards(out["claims"], out["allocation"], limit=12)

    with right:
        # The whole pitch in one button: not a summary of the trace, the
        # trace itself, rebuilt from this run.
        if st.button("How the four agents worked", key="open_trace",
                     type="primary", width='stretch'):
            agent_trace_dialog(out, source)
        st.caption("Every calculation behind this allocation, agent by "
                   "agent, from the live run.")
        st.write("")

        # Impact sits beside the first farm cards now. It is the claim
        # the page is making, and it was below the fold; the log is the
        # evidence, and it is the panel that grows with the run, so it
        # is the one that should absorb the leftover column height.
        section("Impact")
        render_impact(out["scorecard"])

        st.write("")
        section("What the agents did")
        st.caption(f"{out['coordination']['rounds_used']} negotiation "
                   f"round(s)")
        # This run only. The engine's log is rebuilt every rerun and
        # the weather line, if the conditions moved, belongs to the same
        # run — so nothing here survives into the next one.
        # height="stretch" hands this container the column's leftover
        # vertical space, so the log grows with the farm list instead of
        # ending halfway up it.
        with st.container(height="stretch", key="logbox"):
            render_activity_log(([weather_line] if weather_line else [])
                                + out["log"])

        st.write("")
        with st.expander("Show the working for every farm"):
            st.caption("Every number on a card, derived from FAO "
                       "coefficients. Nothing here is hardcoded.")
            render_working(out["claims"], out["allocation"])


if __name__ == "__main__":
    main()