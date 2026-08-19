"""
coordinator.py — AquaFair
AGENT 3
Owner: A

Takes: a list of CLAIM dicts (from farm_agent.py) + total water available
Gives back: the ALLOCATION dict (agreed contract) + a structured agent log

────────────────────────────────────────────────────────────────────────
WHY THE CONTEST TRIGGER IS NOT "below survival minimum"

The obvious trigger — contest if met_survival is False — turns out to be
unreachable. Given optimizer.allocate()'s two-pass design:

  * If total_survival <= total_water, Pass 1 hands EVERY farm its full
    survival minimum, so met_survival is True for everyone. Nobody can
    ever contest.
  * If total_survival > total_water, Pass 1 scales everyone
    proportionally. Every farm is unmet, so every farm escalates by the
    same 1.4x — which scales all the weights equally and leaves the
    proportions unchanged. Rounds 2 and 3 return identical allocations.

Measured on the 4-farm demo set: the flip happens at 319,929 L. Above
it, zero farms contest. Below it, all four do and nothing changes across
rounds. There is no water level at which the loop does anything.

So we trigger on YIELD DAMAGE instead:

    a farm contests if it is below its survival minimum
    OR its projected yield loss exceeds CONTEST_YIELD_LOSS_PCT

That is reachable, it escalates a SUBSET of farms (so Pass 2 proportions
genuinely shift), and it matches what the pitch actually claims: a farm
whose crop is about to take serious damage pushes back and gets more.

Second fix: when total supply is below total survival need, no amount of
renegotiation creates water. We detect that in round 1 and stop, instead
of printing three identical rounds that look like a broken loop.
────────────────────────────────────────────────────────────────────────

OUTPUT CONTRACT — agreed at hour 0. Do not change without telling B,
because app.py renders directly off this shape.

    {
      "allocation": {
          "F001": {
              "survival_L": int, "surplus_L": int, "total_L": int,
              "satisfaction": float,        # 0.0 - 1.0
              "yield_loss_pct": float,
              "priority_score": float,
              "contested": bool,            # contested at ANY round
          }, ...
      },
      "log": [ {"time": "10:31:04", "agent": "Coordinator",
                "message": "..."} , ... ],
      "rounds_used": int,
      "all_survival_met": bool,
      "supply_infeasible": bool,   # True = pool < total survival need

      # One record per negotiation round, in order. Additive — nothing
      # that read this dict before needs to change. The dashboard's
      # agent-trace panel renders from it, because the alternative is
      # parsing the log sentences back into numbers, and a panel whose
      # job is to prove nothing is hardcoded cannot be built on string
      # scraping.
      "rounds": [
          {"round": 1,
           "urgency": {"F001": 1.0, ...},   # multipliers going IN
           "handed_out_L": float,
           "given": {"F001": int, ...},     # litres out of this round
           "contested": [{"farm_id", "crop", "allocated_L",
                          "survival_L", "required_L", "yield_loss_pct",
                          "below_survival"}, ...],
           "escalated": {"F001": 1.4, ...}, # multipliers going OUT
           "outcome": "settled" | "escalated" | "exhausted"
                      | "infeasible" | "baseline",
           "note": str},
          ...
      ],
    }
"""

from datetime import datetime

from optimizer import allocate

MAX_ROUNDS = 3
ESCALATION_FACTOR = 1.4

# A farm contests if its projected yield loss exceeds this. Tune against
# the drought scenario: too high and nothing ever contests, too low and
# every farm contests and the escalation goes uniform again — which is
# the failure mode described at the top of this file.
CONTEST_YIELD_LOSS_PCT = 20.0


def _log(entries, message, agent="Coordinator"):
    """Append one structured log line. app.py colours by `agent`."""
    entries.append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "agent": agent,
        "message": message,
    })


def _satisfaction(given, required):
    """Guarded ratio. A zero-requirement farm (heavy rain covered it) is
    fully satisfied by definition, not a division by zero."""
    if required <= 0:
        return 1.0
    return max(0.0, min(1.0, given / required))


def _yield_loss_pct(claim, given):
    """FAO-33 form: yield loss = Ky * (1 - ETa/ETc).

    This can legitimately exceed 100% when Ky > 1 and the shortfall is
    severe — paddy at Ky 1.35 with no water gives 135%. That is what the
    formula says. app.py should clamp the DISPLAY at 100%; we do not
    clamp here, because impact.py wants the raw figure."""
    sat = _satisfaction(given, claim["water_required_L"])
    return claim["ky"] * (1.0 - sat) * 100.0


def _contesting(results, by_id):
    """Farms pushing back this round: below survival, or facing serious
    yield damage. Returns [(row, is_below_survival), ...]."""
    out = []
    for r in results:
        claim = by_id[r["farm_id"]]
        below = not r["met_survival"]
        damaged = _yield_loss_pct(claim, r["allocated_L"]) > CONTEST_YIELD_LOSS_PCT
        if below or damaged:
            out.append((r, below))
    return out


def _contested_row(r, below, claim):
    """One contesting farm, as data rather than a sentence.

    The trace panel needs numbers it can format itself. Parsing them
    back out of the log strings would make a panel whose entire job is
    to prove nothing is hardcoded depend on string scraping."""
    return {
        "farm_id": r["farm_id"],
        "crop": r["crop"],
        "allocated_L": r["allocated_L"],
        "survival_L": r["survival_minimum_L"],
        "required_L": r["water_required_L"],
        "yield_loss_pct": round(_yield_loss_pct(claim, r["allocated_L"]), 1),
        "below_survival": below,
    }


def _to_contract(results, claims, contested_ids):
    """Convert the optimizer's rows into the agreed ALLOCATION dict.

    The optimizer knows how much each farm got. Splitting that into
    survival vs surplus, and turning it into satisfaction and yield
    loss, happens here so every consumer sees the same numbers."""
    by_id = {c["farm_id"]: c for c in claims}
    allocation = {}

    for r in results:
        fid = r["farm_id"]
        claim = by_id[fid]
        got = r["allocated_L"]
        survival = claim["survival_minimum_L"]

        allocation[fid] = {
            "survival_L":     int(min(got, survival)),
            "surplus_L":      int(max(0, got - survival)),
            "total_L":        int(got),
            "satisfaction":   round(_satisfaction(got, claim["water_required_L"]), 4),
            "yield_loss_pct": round(_yield_loss_pct(claim, got), 1),
            "priority_score": r.get("priority_score", 0),
            "contested":      fid in contested_ids,
        }

    return allocation


def run_coordination(claims, total_water_L, mode="equity"):
    if not claims:
        return {"allocation": {}, "log": [], "rounds_used": 0,
                "all_survival_met": True, "supply_infeasible": False,
                "rounds": []}

    by_id = {c["farm_id"]: c for c in claims}
    urgency = {c["farm_id"]: 1.0 for c in claims}
    contested_ids = set()
    log = []
    results = []
    rounds_used = 0
    rounds = []

    total_survival = sum(c["survival_minimum_L"] for c in claims)
    infeasible = total_survival > total_water_L

    _log(log, f"Pool: {total_water_L:,.0f} L across {len(claims)} farms. "
              f"Survival need: {total_survival:,.0f} L.")

    for round_num in range(1, MAX_ROUNDS + 1):
        rounds_used = round_num
        results = allocate(claims, total_water_L, urgency=urgency, mode=mode)

        # team rule #2 — never hand out more water than exists
        handed_out = sum(r["allocated_L"] for r in results)
        assert handed_out <= total_water_L + 1.0, (
            f"Over-allocation in round {round_num}: {handed_out:,.0f} L "
            f"handed out of {total_water_L:,.0f} L available"
        )

        _log(log, f"Round {round_num}: {handed_out:,.0f} L allocated across "
                  f"{len(results)} farms.", agent="Optimizer")

        # What this round saw and did. Filled in as the round resolves;
        # every branch below closes it before returning, so a record can
        # never be left with an empty outcome.
        record = {
            "round": round_num,
            "urgency": {fid: round(u, 3) for fid, u in urgency.items()},
            "handed_out_L": handed_out,
            "given": {r["farm_id"]: r["allocated_L"] for r in results},
            "contested": [],
            "escalated": {},
            "outcome": "",
            "note": "",
        }
        rounds.append(record)

        # Supply below total survival need — renegotiation cannot create
        # water. Stop after one round and say so, rather than printing
        # three identical rounds.
        if infeasible:
            for r in results:
                contested_ids.add(r["farm_id"])
            record["contested"] = [
                _contested_row(r, True, by_id[r["farm_id"]]) for r in results]
            record["outcome"] = "infeasible"
            record["note"] = (
                f"Supply {total_water_L:,.0f} L is below the total survival "
                f"need of {total_survival:,.0f} L. Every floor was scaled "
                f"proportionally and the loop stopped: renegotiation cannot "
                f"create water.")
            _log(log, f"Supply is {total_water_L:,.0f} L against a survival "
                      f"need of {total_survival:,.0f} L. Every farm is below "
                      f"its floor and water was split proportionally. No "
                      f"reallocation can fix a shortfall this size — stopping "
                      f"after one round.")
            return {
                "allocation": _to_contract(results, claims, contested_ids),
                "log": log,
                "rounds_used": round_num,
                "all_survival_met": False,
                "supply_infeasible": True,
                "rounds": rounds,
            }

        # yield_max deliberately has NO survival floor, so "below
        # survival" is its expected outcome, not a fault to renegotiate.
        # Running the contest loop on it would misrepresent the baseline
        # we are arguing against. One pass, then stop.
        if mode == "yield_max":
            for r in results:
                if not r["met_survival"]:
                    contested_ids.add(r["farm_id"])
            record["contested"] = [
                _contested_row(r, True, by_id[r["farm_id"]])
                for r in results if not r["met_survival"]]
            record["outcome"] = "baseline"
            record["note"] = ("Policy is yield_max: no survival floor, so "
                              "no contest round. Shown as-is.")
            _log(log, "Policy is yield_max: no survival floor, no contest "
                      "round. This is the baseline, shown as-is.")
            return {
                "allocation": _to_contract(results, claims, contested_ids),
                "log": log,
                "rounds_used": round_num,
                "all_survival_met": all(r["met_survival"] for r in results),
                "supply_infeasible": False,
                "rounds": rounds,
            }

        contesting = _contesting(results, by_id)

        if not contesting:
            record["outcome"] = "settled"
            record["note"] = (
                f"No farm is below its survival floor or above "
                f"{CONTEST_YIELD_LOSS_PCT:.0f}% yield loss, so nobody "
                f"contested and the allocation settled in round "
                f"{round_num}.")
            _log(log, f"No farm below survival or above "
                      f"{CONTEST_YIELD_LOSS_PCT:.0f}% yield loss. "
                      f"Allocation settled in round {round_num}.")
            return {
                "allocation": _to_contract(results, claims, contested_ids),
                "log": log,
                "rounds_used": round_num,
                "all_survival_met": True,
                "supply_infeasible": False,
                "rounds": rounds,
            }

        record["contested"] = [_contested_row(r, below, by_id[r["farm_id"]])
                               for r, below in contesting]

        for r, below in contesting:
            fid = r["farm_id"]
            contested_ids.add(fid)
            loss = _yield_loss_pct(by_id[fid], r["allocated_L"])
            reason = (f"below survival ({r['allocated_L']:,.0f} L vs "
                      f"{r['survival_minimum_L']:,.0f} L)" if below
                      else f"facing {loss:.0f}% yield loss")
            _log(log, f"{fid} ({r['crop']}) {reason}. CONTEST.", agent="Farm")

        # Escalate only if there is another round to escalate INTO.
        # Escalating on the final round prints an urgency figure that
        # never gets used, which reads as a bug during the demo.
        if round_num < MAX_ROUNDS:
            for r, _ in contesting:
                fid = r["farm_id"]
                urgency[fid] *= ESCALATION_FACTOR
                record["escalated"][fid] = round(urgency[fid], 3)
                _log(log, f"Escalating {fid} urgency to {urgency[fid]:.2f}x. "
                          f"Re-running optimizer.")
            record["outcome"] = "escalated"
            record["note"] = (
                f"{len(contesting)} farm(s) contested. Their urgency was "
                f"multiplied by {ESCALATION_FACTOR}x and the optimizer "
                f"re-ran with the new weights.")
        else:
            record["outcome"] = "exhausted"
            record["note"] = (
                f"{len(contesting)} farm(s) still contested, but round "
                f"{MAX_ROUNDS} is the last one, so no further escalation "
                f"was applied.")

    still = _contesting(results, by_id)
    _log(log, f"Stopped after {MAX_ROUNDS} rounds. {len(still)} farm(s) still "
              f"contesting — the remaining gap is a supply limit, not an "
              f"allocation one.")

    return {
        "allocation": _to_contract(results, claims, contested_ids),
        "log": log,
        "rounds_used": rounds_used,
        "all_survival_met": all(r["met_survival"] for r in results),
        "supply_infeasible": False,
        "rounds": rounds,
    }


if __name__ == "__main__":
    # manual check — not part of the app
    #
    # ⚠ ONE COMMAND AREA. fake_claims now holds 32 farms across four
    # tanks and canals; pooling them would let Tank A's water reach
    # Tank B's farms, which is exactly what the design forbids.
    from fake_claims import CLAIMS_BY_SOURCE
    from sources import DEFAULT_SOURCE, get_source, deliverable_water_L

    src = get_source(DEFAULT_SOURCE)
    claims = CLAIMS_BY_SOURCE[DEFAULT_SOURCE]
    deliverable = deliverable_water_L(DEFAULT_SOURCE)

    print(f"{src['name']} ({DEFAULT_SOURCE}) — {len(claims)} farms, "
          f"{deliverable:,.0f} L deliverable")

    for label, water in [
        ("FULL",    deliverable),
        ("HALF",    deliverable * 0.5),
        ("CRISIS",  deliverable * 0.2),
    ]:
        out = run_coordination(claims, water)
        print(f"\n=== {label} — {water:,.0f} L | rounds "
              f"{out['rounds_used']} | survival met "
              f"{out['all_survival_met']} | infeasible "
              f"{out['supply_infeasible']} ===")
        for e in out["log"]:
            print(f"  [{e['time']}] {e['agent']:<11} {e['message']}")

        print("\n  round records:")
        for r in out["rounds"]:
            esc = (", ".join(f"{f}->{m}x" for f, m in r["escalated"].items())
                   or "none")
            print(f"    round {r['round']}  {r['outcome']:<11} "
                  f"{r['handed_out_L']:>10,.0f} L  "
                  f"{len(r['contested'])} contesting  escalated: {esc}")

        print()
        for fid, a in out["allocation"].items():
            flag = "  CONTESTED" if a["contested"] else ""
            print(f"  {fid}  {a['total_L']:>8,} L  "
                  f"sat {a['satisfaction']:>5.0%}  "
                  f"loss {a['yield_loss_pct']:>6.1f}%{flag}")