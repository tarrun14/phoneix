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

import db

def load_sources():
    """Every command area we can allocate for.

    Returns {source_id: record}
    """
    return db.query_sources()


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

