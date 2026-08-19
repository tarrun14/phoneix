"""
sources.py — AquaFair
Tank and canal records for the command areas we allocate across.

WHY THIS IS NOT IN constants.py
constants.py holds PUBLISHED REFERENCE DATA — FAO crop coefficients and
yield response factors. Those are citable, they do not change, and they
are the same in Thanjavur as in Tirunelveli.

What is in this file is the opposite on every count:
  * it changes daily (a storage reading is a gauge reading)
  * it is specific to one district
  * none of it is published anywhere — we made it up
In deployment none of these numbers are typed by anyone. They come from
the PWD tank register and a daily level reading, through load_sources().

THE SEAM
load_sources() is the only function that knows where the data lives.
Swapping simulation for a real database means replacing ONE function
body. Nothing that calls it changes:

    def load_sources():
        rows = db.query("SELECT * FROM tank_register WHERE district = ?")
        return {r.id: {...} for r in rows}

Everything downstream — generate.py, app.py — goes through
load_sources(), get_source() and deliverable_water(). None of them
touch the dict directly.

CONVEYANCE EFFICIENCY — the field that is usually left out
Water RELEASED is not water DELIVERED. An unlined earthen channel loses
a third of a release to seepage and evaporation before it reaches a
field. Indian canal systems commonly run 55-70%; short lined tank
sluices do better.

    deliverable = live_storage_L x conveyance_efficiency

This matters more than it looks. A canal holding 15,500,000 L at 62%
can only deliver 9,610,000 L. Allocating the stored figure would
promise farmers nearly six million litres that never arrive.

NO WATER CROSSES BETWEEN SOURCES
A district is many independent command areas, each with its own Water
User Association. Farms under Tank A have no claim on Tank B's water,
and a WUA constituted for one command area has no standing over
another's — the same authority limit that stops us touching private
borewells. Allocation always runs against ONE source's farm list.

STORAGE IS SIZED FROM COMMAND AREA, NOT PICKED
One 4-day cycle in drought needs roughly
    ETo 6.2 x Kc 1.1 x 4 days = 27.3 mm = 273,000 L per hectare.
Live storage here is about 60% of one cycle's need, which puts a
drought run in the 40-50% shortfall band that deficit years actually
show. Capacity is roughly 1.5x live storage — a tank at full supply
level holds more than it currently does.

The demo set is 4 farms totalling 3.5 ha, which is why T01 is a small
village tank rather than a canal. A district-scale canal with 4 farms
on it would have no shortage and nothing to demonstrate.
"""

# ── Simulated records. Replace with a real query, not by editing. ──
_SIMULATED = {
    "T01": {
        "name": "Periya Eri",
        "type": "tank",
        "capacity_L": 900_000,
        "live_storage_L": 700_000,
        "conveyance_efficiency": 0.80,   # short sluice, mostly lined
        "command_area_ha": 4,
        "wua": "Periya Eri WUA",
    },
    "T02": {
        "name": "Kanmoi Chinna Eri",
        "type": "tank",
        "capacity_L": 2_600_000,
        "live_storage_L": 1_800_000,
        "conveyance_efficiency": 0.72,   # earthen field channels
        "command_area_ha": 11,
        "wua": "Chinna Eri WUA",
    },
    "C01": {
        "name": "Kalingarayan Branch Canal",
        "type": "canal",
        "capacity_L": 22_000_000,
        "live_storage_L": 15_500_000,
        "conveyance_efficiency": 0.62,   # long unlined distributary
        "command_area_ha": 72,
        "wua": "Lower Branch WUA",
    },
    "C02": {
        "name": "Thottiyam Distributary",
        "type": "canal",
        "capacity_L": 12_000_000,
        "live_storage_L": 8_400_000,
        "conveyance_efficiency": 0.68,
        "command_area_ha": 41,
        "wua": "Thottiyam WUA",
    },
}

REQUIRED_FIELDS = ("name", "type", "capacity_L", "live_storage_L",
                   "conveyance_efficiency", "command_area_ha", "wua")


def load_sources():
    """Every command area we can allocate for.

    ⚠ THIS IS THE SEAM. Right now it returns simulated records. In
    deployment it queries the PWD tank register and the latest gauge
    reading. Replacing this function body is the entire migration —
    every caller goes through here.

    Returns {source_id: record}
    """
    return dict(_SIMULATED)


def list_sources():
    """Source ids, tanks before canals, for a stable dropdown order."""
    return sorted(load_sources(),
                  key=lambda s: (load_sources()[s]["type"] != "tank", s))


def get_source(source_id):
    sources = load_sources()
    if source_id not in sources:
        raise KeyError(
            f"Unknown source {source_id!r}. Known: {sorted(sources)}")
    return sources[source_id]


def deliverable_water_L(source_id):
    """Water that will actually REACH the fields.

    Always allocate against this, never against live_storage_L. The
    difference is lost to seepage and evaporation in the channel, and
    promising it to farmers is promising water that never arrives.
    """
    s = get_source(source_id)
    return s["live_storage_L"] * s["conveyance_efficiency"]


def conveyance_loss_L(source_id):
    """The gap between released and delivered."""
    s = get_source(source_id)
    return s["live_storage_L"] - deliverable_water_L(source_id)


DEFAULT_SOURCE = "T01"


# ── Integrity checks — fire at import, not mid-demo ───────────────
_loaded = load_sources()
for _sid, _rec in _loaded.items():
    _missing = set(REQUIRED_FIELDS) - set(_rec)
    assert not _missing, f"{_sid} is missing fields: {sorted(_missing)}"
    assert _rec["live_storage_L"] <= _rec["capacity_L"], \
        f"{_sid}: live storage exceeds capacity"
    assert 0.0 < _rec["conveyance_efficiency"] <= 1.0, \
        f"{_sid}: conveyance efficiency out of range"
    assert _rec["command_area_ha"] > 0, f"{_sid}: command area must be > 0"
assert DEFAULT_SOURCE in _loaded


if __name__ == "__main__":
    print(f"{'id':<5}{'name':<28}{'type':<7}{'ha':>5}"
          f"{'stored':>12}{'eff':>6}{'deliverable':>13}{'lost':>12}")
    for sid in list_sources():
        s = get_source(sid)
        print(f"{sid:<5}{s['name']:<28}{s['type']:<7}"
              f"{s['command_area_ha']:>5}{s['live_storage_L']:>12,}"
              f"{s['conveyance_efficiency']:>6.2f}"
              f"{deliverable_water_L(sid):>13,.0f}"
              f"{conveyance_loss_L(sid):>12,.0f}")