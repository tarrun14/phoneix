"""
sources.py — AquaFair
Tank and canal records for the command areas we allocate across.

The records themselves live in a SQLite database, NOT in this file.
db.py owns the connection; this file owns the domain questions.

WHY A FILE AND NOT A PYTHON DICT
constants.py holds PUBLISHED REFERENCE DATA — FAO crop coefficients and
yield response factors. Those are citable, they do not change, and they
are the same in Thanjavur as in Tirunelveli. They belong in code, with
their citations beside them.

Tank records are the opposite on every count:
  * they change daily — a storage figure is a gauge reading
  * they are specific to one district
  * none of them are published anywhere; we made them up
An irrigation officer updating a water level should not be editing
Python. They belong in a table, with constraints that refuse a gauge
reading above full supply level at the write rather than three modules
later when an allocation looks wrong.

THE SEAM
load_sources() is the only function that knows where the data lives,
and it delegates to db.query_sources(). Moving from SQLite to Oracle or
Postgres means changing db.connect() and the driver import — the SELECT
is standard SQL and stays as it is.

Everything downstream — generate.py, app.py, main.py — goes through
load_sources(), get_source() and deliverable_water_L(). None of them
open a connection or touch the dict directly.

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
Live storage in the file is about 60% of one cycle's need, which puts a
drought run in the 40-50% shortfall band that deficit years actually
show. Capacity is roughly 1.5x live storage — a tank at full supply
level holds more than it currently does.

The demo set is 4 farms totalling 3.5 ha, which is why T01 is a small
village tank rather than a canal. A district-scale canal with 4 farms
on it would have no shortage and nothing to demonstrate.
"""

import os

import db

REQUIRED_FIELDS = ("name", "type", "capacity_L", "live_storage_L",
                   "conveyance_efficiency", "command_area_ha", "wua")

DEFAULT_SOURCE = "T01"

# Read once at import. Four rows, and nothing writes during a run, so
# re-querying on every call would be hundreds of connections per
# dashboard rerun for no benefit. Pass refresh=True after an update.
_CACHE = None


def load_sources(refresh=False):
    """Every command area we can allocate for.

    ⚠ THIS IS THE SEAM. It asks db.query_sources() for rows and checks
    them. Swapping SQLite for Oracle happens in db.connect(); this
    function does not change, and neither does anything that calls it.

    The checks below duplicate the CHECK constraints in schema.sql on
    purpose. The database refuses bad writes; this refuses bad reads —
    from a hand-edited file, a partial restore, or a future loader that
    is not SQL at all. Belt and braces on the one input the whole
    allocation rests on.

    Returns {source_id: record}
    """
    global _CACHE
    if _CACHE is not None and not refresh:
        return dict(_CACHE)

    data = db.query_sources()

    if not data:
        raise ValueError("The sources table is empty — no command areas "
                         "to allocate for. Rebuild: python db.py --rebuild")

    for sid, rec in data.items():
        missing = set(REQUIRED_FIELDS) - set(rec)
        if missing:
            raise ValueError(f"source {sid} is missing {sorted(missing)}")
        if rec["live_storage_L"] > rec["capacity_L"]:
            raise ValueError(
                f"{sid}: live_storage_L ({rec['live_storage_L']:,}) exceeds "
                f"capacity_L ({rec['capacity_L']:,})")
        if not 0 < rec["conveyance_efficiency"] <= 1:
            raise ValueError(
                f"{sid}: conveyance_efficiency must be between 0 and 1, "
                f"got {rec['conveyance_efficiency']}")
        if rec["command_area_ha"] <= 0:
            raise ValueError(f"{sid}: command_area_ha must be > 0")
        if rec["live_storage_L"] < 0:
            raise ValueError(f"{sid}: live_storage_L must be >= 0")

    if DEFAULT_SOURCE not in data:
        raise ValueError(
            f"No {DEFAULT_SOURCE!r} in the sources table — the dashboard "
            f"opens on it. Change DEFAULT_SOURCE or add the row.")

    _CACHE = data
    return dict(data)


def list_sources():
    """Source ids, tanks before canals, for a stable dropdown order.

    The SELECT already orders them this way; re-sorting here means the
    order survives a loader that does not."""
    loaded = load_sources()
    return sorted(loaded, key=lambda s: (loaded[s]["type"] != "tank", s))


def get_source(source_id):
    loaded = load_sources()
    if source_id not in loaded:
        raise KeyError(
            f"Unknown source {source_id!r}. Known: {sorted(loaded)}")
    return loaded[source_id]


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


# Fail at import, not mid-demo, if the database is missing or malformed.
# db.fetch_sources() builds it from schema.sql if it is not there, so a
# fresh clone of the repo works with no setup step.
load_sources()


if __name__ == "__main__":
    print(f"{os.path.basename(db.DB_PATH)}\n")
    print(f"{'id':<5}{'name':<28}{'type':<7}{'ha':>5}"
          f"{'stored':>12}{'eff':>6}{'deliverable':>13}{'lost':>12}")
    for sid in list_sources():
        s = get_source(sid)
        print(f"{sid:<5}{s['name']:<28}{s['type']:<7}"
              f"{s['command_area_ha']:>5}{s['live_storage_L']:>12,}"
              f"{s['conveyance_efficiency']:>6.2f}"
              f"{deliverable_water_L(sid):>13,.0f}"
              f"{conveyance_loss_L(sid):>12,.0f}")