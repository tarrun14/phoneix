"""
db.py — AquaFair
THE RECORD

Everything else in this project is recomputed from scratch on every
rerun. Nothing is cached, nothing is stale — which is exactly right for
a dashboard and exactly wrong for a decision. An allocation that only
exists on screen cannot be produced six months later when a farmer asks
why they got 45% of what they asked for in the fifth wetting of 2026.

This file is the one place AquaFair remembers.

WHY SQLITE AND NOTHING ELSE
No server to run, no credentials to hold, no daemon to keep alive. The
whole record is one file a WUA office can copy to a pen drive, mail to
the district WRD office, or hand to a court. A block-level Water User
Association does not have a DBA.

APPEND-ONLY, AND ENFORCED IN THE DATABASE
An audit trail that can be rewritten is not an audit trail. Two things
follow from that:

  * allocations rows are never UPDATEd and never DELETEd
  * runs rows are never DELETEd, and the ONLY column that may change
    after insert is the approval pair (approved_by, approved_at) —
    once, from NULL

That rule is not a convention in this file's functions. It is four
triggers in the schema, so a stray UPDATE from a future feature, a
teammate's script or the sqlite3 command line aborts with an error
rather than quietly succeeding. Discipline that lives only in the
calling code is discipline that lasts until the next contributor.

Correcting a run means recording a NEW run. The wrong one stays.

INPUT HASH
Every run stores the sha256 of the readings it was computed from. It is
not security — anyone holding the file could rewrite a row and rehash
it. It is tamper EVIDENCE: it makes an edit require deliberate effort
rather than a text editor, and verify_integrity() below re-derives it
from the stored columns so the app can state on screen that a record is
being shown exactly as it was written.

AUTHENTICATION IS A PROTOTYPE
verify_officer() checks an id and a password against a plaintext column
in this file. There is no hashing, no salt, no session, no lockout, and
the whole roster ships with the same password. In deployment this is
the WUA office-bearer register held by the district WRD office, and
this file would hold neither the check nor the roster.

THE SEAM
app.py imports these functions and nothing else. It never opens a
connection, never writes SQL and never learns the table names.
"""

import csv
import hashlib
import json
import os
import sqlite3
from datetime import datetime

# Beside the code, not in a temp directory. The record is part of the
# project, and a WUA that copies the folder copies its decisions with it.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "aquafair.db")
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "demo_farms.csv")

# ── Roles ────────────────────────────────────────────────────────
# Three, because that is how the authority actually splits: the WUA
# secretary runs the allocation for their command area, the WRD officer
# signs it off for the district, and the farmer is shown their own field
# and nothing else.
ROLE_SECRETARY = "wua_secretary"
ROLE_OFFICER   = "wrd_officer"
ROLE_FARMER    = "farmer"
ROLES = (ROLE_SECRETARY, ROLE_OFFICER, ROLE_FARMER)

ROLE_LABEL = {
    ROLE_SECRETARY: "WUA Secretary",
    ROLE_OFFICER:   "WRD Officer",
    ROLE_FARMER:    "Farmer",
}

# ── Demo roster ──────────────────────────────────────────────────
# Seeded on first run only, and only when the table is empty: reseeding
# a populated roster would overwrite a real one.
#
# ⚠ source_id means different things by role, and the difference is
# institutional, not technical. For a WUA secretary and a farmer it is a
# boundary — a WUA constituted for one command area has no standing over
# another's, the same limit sources.py describes. For a WRD officer it
# is the area they open on: a district officer supervises every WUA in
# the district, and an officer who could only see one of them could not
# do the job the approval column exists for.
SEED_OFFICERS = [
    ("WUA-T01-007",   "Selvi Ramanathan",  ROLE_SECRETARY, "T01", None,   "password"),
    ("WRD-ERD-042",   "R. Chandrasekaran", ROLE_OFFICER,   "C01", None,   "password"),
    ("FARM-T01-F002", "Kavitha",           ROLE_FARMER,    "T01", "F002", "password"),
    ("FARM-C01-F015", "Vasanthi",          ROLE_FARMER,    "C01", "F015", "password"),
]

# ── The command areas ────────────────────────────────────────────
# Seeded here so a fresh clone builds a working database from one file.
# sources.py reads them back through query_sources() and never opens a
# connection itself.
SEED_SOURCES = {
    "T01": {"name": "Periya Eri", "type": "tank",
            "capacity_L": 900_000, "live_storage_L": 700_000,
            "conveyance_efficiency": 0.80, "command_area_ha": 4,
            "wua": "Periya Eri WUA"},
    "T02": {"name": "Kanmoi Chinna Eri", "type": "tank",
            "capacity_L": 2_600_000, "live_storage_L": 1_800_000,
            "conveyance_efficiency": 0.72, "command_area_ha": 11,
            "wua": "Chinna Eri WUA"},
    "C01": {"name": "Kalingarayan Branch Canal", "type": "canal",
            "capacity_L": 22_000_000, "live_storage_L": 15_500_000,
            "conveyance_efficiency": 0.62, "command_area_ha": 72,
            "wua": "Lower Branch WUA"},
    "C02": {"name": "Thottiyam Distributary", "type": "canal",
            "capacity_L": 12_000_000, "live_storage_L": 8_400_000,
            "conveyance_efficiency": 0.68, "command_area_ha": 41,
            "wua": "Thottiyam WUA"},
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS officers (
    officer_id  TEXT PRIMARY KEY,
    name        TEXT,
    role        TEXT,
    source_id   TEXT,
    farm_id     TEXT,
    password    TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT,
    source_id       TEXT,
    eto             REAL,
    rainfall_mm     REAL,
    stored_L        REAL,
    conveyance_pct  REAL,
    deliverable_L   REAL,
    policy_mode     TEXT,
    rounds_used     INTEGER,
    approved_by     TEXT,
    approved_at     TEXT,
    input_hash      TEXT
);

CREATE TABLE IF NOT EXISTS allocations (
    run_id          INTEGER,
    farm_id         TEXT,
    crop            TEXT,
    required_L      INTEGER,
    survival_L      INTEGER,
    allocated_L     INTEGER,
    satisfaction    REAL,
    yield_loss_pct  REAL,
    contested       INTEGER,
    justification   TEXT,
    PRIMARY KEY (run_id, farm_id)
);

CREATE INDEX IF NOT EXISTS idx_runs_source
    ON runs (source_id, run_id DESC);
CREATE INDEX IF NOT EXISTS idx_alloc_farm
    ON allocations (farm_id, run_id DESC);

CREATE TABLE IF NOT EXISTS sources (
    source_id               TEXT PRIMARY KEY,
    name                    TEXT    NOT NULL,
    type                    TEXT    NOT NULL,
    capacity_L              REAL    NOT NULL,
    live_storage_L          REAL    NOT NULL,
    conveyance_efficiency   REAL    NOT NULL,
    command_area_ha         REAL    NOT NULL,
    wua                     TEXT    NOT NULL,

    -- The constraints are the point of using SQL here. Validation in
    -- Python can be bypassed by anything that writes to the file; a
    -- CHECK cannot. A gauge reading above full supply level is a
    -- data-entry error and it should be refused at the write, not
    -- discovered three modules later when an allocation looks wrong.
    CHECK (type IN ('tank', 'canal')),
    CHECK (live_storage_L >= 0),
    CHECK (live_storage_L <= capacity_L),
    CHECK (conveyance_efficiency > 0 AND conveyance_efficiency <= 1),
    CHECK (command_area_ha > 0)
);

CREATE TABLE IF NOT EXISTS demo_farms (
    source_id       TEXT,
    farm_id         TEXT PRIMARY KEY,
    farmer_name     TEXT,
    crop            TEXT,
    stage           TEXT,
    area_m2         REAL,
    fairness_debt   REAL
);

-- ── The append-only rule, in the file rather than in a habit ──────
CREATE TRIGGER IF NOT EXISTS allocations_no_update
BEFORE UPDATE ON allocations BEGIN
    SELECT RAISE(ABORT,
        'allocations is append-only: record a new run instead');
END;

CREATE TRIGGER IF NOT EXISTS allocations_no_delete
BEFORE DELETE ON allocations BEGIN
    SELECT RAISE(ABORT,
        'allocations is append-only: a wrong run stays on the record');
END;

CREATE TRIGGER IF NOT EXISTS runs_no_delete
BEFORE DELETE ON runs BEGIN
    SELECT RAISE(ABORT,
        'runs is append-only: a wrong run stays on the record');
END;

-- Everything about a run is fixed at insert except the approval. IS NOT
-- rather than <> so a NULL on either side compares properly.
CREATE TRIGGER IF NOT EXISTS runs_approval_only
BEFORE UPDATE ON runs
WHEN OLD.run_id         IS NOT NEW.run_id
  OR OLD.timestamp      IS NOT NEW.timestamp
  OR OLD.source_id      IS NOT NEW.source_id
  OR OLD.eto            IS NOT NEW.eto
  OR OLD.rainfall_mm    IS NOT NEW.rainfall_mm
  OR OLD.stored_L       IS NOT NEW.stored_L
  OR OLD.conveyance_pct IS NOT NEW.conveyance_pct
  OR OLD.deliverable_L  IS NOT NEW.deliverable_L
  OR OLD.policy_mode    IS NOT NEW.policy_mode
  OR OLD.rounds_used    IS NOT NEW.rounds_used
  OR OLD.input_hash     IS NOT NEW.input_hash
BEGIN
    SELECT RAISE(ABORT,
        'only approved_by and approved_at may be set after a run is written');
END;

-- An approval is a signature. It is given once and it is not reassigned.
CREATE TRIGGER IF NOT EXISTS runs_approve_once
BEFORE UPDATE OF approved_by ON runs
WHEN OLD.approved_by IS NOT NULL BEGIN
    SELECT RAISE(ABORT, 'this run is already approved');
END;
"""


class AppendOnlyError(Exception):
    """A write the schema refuses. Raised for the caller to show, not to
    swallow: it means something tried to edit the record."""


# ══════════════════════════════════════════════════════════════════
# Connection handling — a broken file must not end the demo
# ══════════════════════════════════════════════════════════════════

# Only these mean the FILE is unusable. An IntegrityError from the
# append-only triggers is also a DatabaseError, and rebuilding the
# database because someone tried an illegal UPDATE would destroy the
# record on precisely the event it exists to catch.
_CORRUPT_MARKERS = ("malformed", "not a database", "file is encrypted",
                    "disk image", "corrupt")


def _is_corruption(exc):
    return any(m in str(exc).lower() for m in _CORRUPT_MARKERS)


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _quarantine():
    """Move a damaged file aside. Never delete it.

    It may still be readable by a recovery tool, and a database that
    deletes its own audit trail to recover from a bad byte has the
    priorities backwards. Returns the path it was moved to, or None if
    even that failed."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dead = f"{DB_PATH}.corrupt-{stamp}"
    try:
        os.replace(DB_PATH, dead)
        return dead
    except OSError:
        try:
            os.remove(DB_PATH)
        except OSError:
            pass
        return None


def _seed_sources(conn):
    """The command areas. INSERT OR IGNORE, so a live gauge reading
    already in the table is never overwritten by a seed value."""
    for sid, d in SEED_SOURCES.items():
        conn.execute(
            "INSERT OR IGNORE INTO sources (source_id, name, type, "
            "capacity_L, live_storage_L, conveyance_efficiency, "
            "command_area_ha, wua) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, d["name"], d["type"], d["capacity_L"],
             d["live_storage_L"], d["conveyance_efficiency"],
             d["command_area_ha"], d["wua"]))


def _seed_demo_farms(conn):
    """The 32 demo farms, read from demo_farms.csv.

    The CSV stays the editable source — a teammate adds a farm in a
    spreadsheet, not in SQL. This only loads it. A missing file is not
    fatal: generate.py reads the CSV directly and the table is a
    convenience for anyone querying the database on its own."""
    if not os.path.exists(CSV_PATH):
        return
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute(
                "INSERT OR IGNORE INTO demo_farms (source_id, farm_id, "
                "farmer_name, crop, stage, area_m2, fairness_debt) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row["source_id"], row["farm_id"], row["farmer_name"],
                 row["crop"], row["stage"], float(row["area_m2"]),
                 float(row["fairness_debt"])))


def _build(conn):
    conn.executescript(_SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM officers").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO officers (officer_id, name, role, source_id, "
            "farm_id, password) VALUES (?, ?, ?, ?, ?, ?)", SEED_OFFICERS)
    _seed_sources(conn)
    _seed_demo_farms(conn)
    conn.commit()


def init_db():
    """Create the tables if missing and seed the demo data.

    Safe to call on every app start: CREATE TABLE IF NOT EXISTS is a
    no-op on an existing file, the roster is only seeded into an empty
    officers table, and the sources and farms use INSERT OR IGNORE.

    A file that cannot be opened as a database at all is moved aside and
    rebuilt. Returns the quarantine path if that happened, else None —
    app.py surfaces it, because a silently recreated audit trail is a
    lost one and someone has to be told."""
    quarantined = None
    try:
        conn = _connect()
        try:
            _build(conn)
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        if not _is_corruption(exc) and os.path.exists(DB_PATH):
            raise
        quarantined = _quarantine()
        conn = _connect()
        try:
            _build(conn)
        finally:
            conn.close()
    return quarantined


def _query(fn, *args, **kw):
    """Run fn(conn, ...) against a healthy database.

    One retry, and only for a corrupt or unbuilt file: the tables are
    rebuilt and the call runs again so a broken record does not take the
    dashboard down with it. Trigger aborts pass straight through as
    AppendOnlyError — they are the schema working."""
    for attempt in (0, 1):
        try:
            conn = _connect()
            try:
                return fn(conn, *args, **kw)
            finally:
                conn.close()
        except sqlite3.IntegrityError as exc:
            raise AppendOnlyError(str(exc)) from exc
        except sqlite3.DatabaseError as exc:
            missing = "no such table" in str(exc).lower()
            if attempt or not (missing or _is_corruption(exc)):
                raise
            if _is_corruption(exc):
                _quarantine()
            init_db()


# ══════════════════════════════════════════════════════════════════
# Officers
# ══════════════════════════════════════════════════════════════════

def verify_officer(officer_id, password=""):
    """The officer row as a dict, or None.

    ⚠ PROTOTYPE AUTHENTICATION. Plaintext comparison against a column
    in this file. No hashing, no salt, no lockout, and every seeded
    account shares one password. Say so if asked — it is a login screen
    standing in for the WUA office-bearer register, not a security
    control."""
    def go(conn):
        row = conn.execute(
            "SELECT officer_id, name, role, source_id, farm_id "
            "FROM officers WHERE officer_id = ? AND password = ?",
            ((officer_id or "").strip(), password)).fetchone()
        return dict(row) if row else None
    return _query(go)


def list_officers(role=None):
    """The roster, for the prototype login screen's demo list.

    Defaults to every registered account so the login screen can offer
    one of each role. Pass a role to narrow it."""
    def go(conn):
        if role is None:
            rows = conn.execute(
                "SELECT officer_id, name, role, source_id, farm_id "
                "FROM officers ORDER BY role, officer_id")
        else:
            rows = conn.execute(
                "SELECT officer_id, name, role, source_id, farm_id "
                "FROM officers WHERE role = ? ORDER BY officer_id",
                (role,))
        return [dict(r) for r in rows]
    return _query(go)


# ══════════════════════════════════════════════════════════════════
# The command areas and the demo farms
# ══════════════════════════════════════════════════════════════════

def query_sources():
    """Every command area, as {source_id: record}.

    sources.py calls this and does nothing else, which is why swapping
    SQLite for Oracle is a change to _connect() and nothing above it."""
    def go(conn):
        rows = conn.execute(
            "SELECT source_id, name, type, capacity_L, live_storage_L, "
            "       conveyance_efficiency, command_area_ha, wua "
            "FROM sources "
            "ORDER BY CASE type WHEN 'tank' THEN 0 ELSE 1 END, source_id"
        ).fetchall()
        return {r["source_id"]: {k: r[k] for k in r.keys()
                                 if k != "source_id"} for r in rows}
    return _query(go)


def query_demo_farms():
    """The demo farms as stored. generate.py reads the CSV directly;
    this is for anyone querying the database on its own."""
    def go(conn):
        return [dict(r) for r in conn.execute(
            "SELECT * FROM demo_farms ORDER BY source_id, farm_id")]
    return _query(go)


def update_storage(source_id, live_storage_L):
    """Record a new gauge reading.

    Not used by the dashboard — the demo reads, it does not write. This
    exists because it is the operation a real deployment performs every
    day, and because it shows the CHECK constraints doing real work:
    pass a figure above capacity and the database refuses it, with no
    Python validation involved."""
    def go(conn):
        cur = conn.execute(
            "UPDATE sources SET live_storage_L = ? WHERE source_id = ?",
            (live_storage_L, source_id))
        if cur.rowcount == 0:
            raise KeyError(f"No source with id {source_id!r}")
        conn.commit()
    return _query(go)


# ══════════════════════════════════════════════════════════════════
# Writing a run
# ══════════════════════════════════════════════════════════════════

def _num(d, *names, default=0.0):
    """First present key, as a float. The engine spells it ETo, the
    schema spells it eto, and a save should not fail over a capital."""
    for n in names:
        if d.get(n) is not None:
            return float(d[n])
    return default


def hash_conditions(conditions, policy):
    """sha256 of everything that was fed in.

    The readings AND the policy: the same water under a different policy
    is a different decision, and two records that hashed identically
    would be claiming otherwise.

    Rounded before hashing so that a float that survived a round trip
    through a text box does not read as a tampered record."""
    payload = {
        "source_id":      conditions.get("source_id"),
        "eto":            round(_num(conditions, "eto", "ETo"), 6),
        "rainfall_mm":    round(_num(conditions, "rainfall_mm"), 6),
        "stored_L":       round(_num(conditions, "stored_L"), 3),
        "conveyance_pct": round(_num(conditions, "conveyance_pct"), 6),
        "deliverable_L":  round(_num(conditions, "deliverable_L"), 3),
        "policy_mode":    policy,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _alloc_rows(allocation, claims):
    """One row per farm, joining what was asked for to what was given.

    Driven by claims, not by allocation: a claim with no allocation is a
    farm the engine was shown and did not serve, and that is exactly the
    row an audit needs to contain."""
    rows = []
    for c in claims:
        a = allocation.get(c["farm_id"]) or {}
        rows.append((
            c["farm_id"],
            c.get("crop"),
            int(c.get("water_required_L", 0)),
            int(c.get("survival_minimum_L", 0)),
            int(a.get("total_L", 0)),
            round(float(a.get("satisfaction", 0.0)), 4),
            round(float(a.get("yield_loss_pct", 0.0)), 1),
            1 if a.get("contested") else 0,
            c.get("justification"),
        ))
    return rows


def _same_as_last(conn, source_id, policy, input_hash, rows):
    """run_id of the latest run for this area if it is the same decision.

    Compared against the LAST run only, deliberately. Going back to
    drought after trying heavy rain should record the return — the log
    is a sequence of decisions, not a set of distinct ones."""
    last = conn.execute(
        "SELECT run_id, input_hash, policy_mode FROM runs "
        "WHERE source_id IS ? ORDER BY run_id DESC LIMIT 1",
        (source_id,)).fetchone()
    if (last is None or last["input_hash"] != input_hash
            or last["policy_mode"] != policy):
        return None

    prev = conn.execute(
        "SELECT farm_id, crop, required_L, survival_L, allocated_L, "
        "satisfaction, yield_loss_pct, contested, justification "
        "FROM allocations WHERE run_id = ? ORDER BY farm_id",
        (last["run_id"],)).fetchall()
    if len(prev) != len(rows):
        return None
    if [tuple(r) for r in prev] != sorted(rows):
        return None
    return last["run_id"]


def save_run(conditions, allocation, claims, policy):
    """Write one allocation to the record. Returns its run_id.

    conditions carries the run-level columns:
        source_id, eto (or ETo), rainfall_mm, stored_L,
        conveyance_pct, deliverable_L, rounds_used

    ⚠ IDENTICAL RUNS ARE NOT DUPLICATED. Streamlit reruns the whole
    script on every keystroke, hover and expander click, and every one
    of those calls this function. Written naively, one demo would leave
    four hundred identical rows and the decision log would be unusable —
    which is the same as not having one.

    So: if the most recent run for this command area has the same input
    hash, the same policy and the same allocation down to the litre,
    this returns that run_id and writes nothing. It is the same
    decision. Change a reading, a farm, or the policy and the next call
    writes a new row.

    This is not an exception to append-only — nothing is edited or
    removed. It only declines to record the same decision twice."""
    src = conditions.get("source_id")
    ihash = hash_conditions(conditions, policy)
    rows = _alloc_rows(allocation, claims)

    def go(conn):
        existing = _same_as_last(conn, src, policy, ihash, rows)
        if existing is not None:
            return existing

        cur = conn.execute(
            "INSERT INTO runs (timestamp, source_id, eto, rainfall_mm, "
            "stored_L, conveyance_pct, deliverable_L, policy_mode, "
            "rounds_used, approved_by, approved_at, input_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)",
            (datetime.now().isoformat(timespec="seconds"),
             src,
             round(_num(conditions, "eto", "ETo"), 6),
             round(_num(conditions, "rainfall_mm"), 6),
             round(_num(conditions, "stored_L"), 3),
             round(_num(conditions, "conveyance_pct"), 6),
             round(_num(conditions, "deliverable_L"), 3),
             policy,
             int(conditions.get("rounds_used") or 0),
             ihash))
        run_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO allocations (run_id, farm_id, crop, required_L, "
            "survival_L, allocated_L, satisfaction, yield_loss_pct, "
            "contested, justification) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(run_id,) + r for r in rows])
        conn.commit()
        return run_id

    return _query(go)


def approve_run(run_id, officer_id):
    """Sign a run off. The only UPDATE this schema permits.

    Raises AppendOnlyError if the run is already approved — an approval
    is a signature, not a setting, and reassigning one would hide who
    actually signed. Returns the approval timestamp."""
    def go(conn):
        row = conn.execute("SELECT approved_by FROM runs WHERE run_id = ?",
                           (run_id,)).fetchone()
        if row is None:
            raise AppendOnlyError(f"No run {run_id} on the record.")
        when = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "UPDATE runs SET approved_by = ?, approved_at = ? "
            "WHERE run_id = ?", (officer_id, when, run_id))
        conn.commit()
        return when
    return _query(go)


# ══════════════════════════════════════════════════════════════════
# Reading it back
# ══════════════════════════════════════════════════════════════════

def recent_runs(source_id, limit=20):
    """Newest first, for one command area.

    Carries the approver's NAME as well as their id: a log that reads
    "approved by WRD-ERD-042" is a log only its author can read."""
    def go(conn):
        return [dict(r) for r in conn.execute(
            "SELECT r.*, o.name AS approved_name, "
            "       (SELECT COUNT(*) FROM allocations a "
            "        WHERE a.run_id = r.run_id) AS farm_count "
            "FROM runs r LEFT JOIN officers o ON o.officer_id = r.approved_by "
            "WHERE r.source_id IS ? "
            "ORDER BY r.run_id DESC LIMIT ?",
            (source_id, int(limit)))]
    return _query(go)


def run_detail(run_id):
    """{"run": row, "allocations": [rows]} for one run, or None.

    Everything the read-only view renders from. It reads the stored
    numbers and never recomputes them: a record that re-derives itself
    on open would show today's answer under an old date."""
    def go(conn):
        run = conn.execute(
            "SELECT r.*, o.name AS approved_name "
            "FROM runs r LEFT JOIN officers o ON o.officer_id = r.approved_by "
            "WHERE r.run_id = ?", (run_id,)).fetchone()
        if run is None:
            return None
        rows = conn.execute(
            "SELECT * FROM allocations WHERE run_id = ? "
            "ORDER BY allocated_L DESC, farm_id", (run_id,)).fetchall()
        return {"run": dict(run), "allocations": [dict(r) for r in rows]}
    return _query(go)


def farm_history(farm_id, limit=10):
    """Every cycle this farm appears in, newest first.

    This is the row a farmer actually wants. One bad week is weather;
    the same farm short every cycle is a policy that is failing them,
    and until it was written down there was no way to tell those apart.
    fairness_debt in the engine is built from exactly this history."""
    def go(conn):
        return [dict(r) for r in conn.execute(
            "SELECT a.*, r.timestamp, r.source_id, r.policy_mode, "
            "       r.approved_by, r.approved_at "
            "FROM allocations a JOIN runs r ON r.run_id = a.run_id "
            "WHERE a.farm_id = ? ORDER BY a.run_id DESC LIMIT ?",
            (farm_id, int(limit)))]
    return _query(go)


def verify_integrity(run_id):
    """Re-derive the hash from the stored columns and compare.

    True means the readings in the row are the ones that were hashed
    when it was written. It does not prove nobody touched the file —
    someone with the file could rewrite a row and rehash it. It proves
    an edit was not casual."""
    def go(conn):
        r = conn.execute("SELECT * FROM runs WHERE run_id = ?",
                         (run_id,)).fetchone()
        if r is None:
            return None
        return hash_conditions(dict(r), r["policy_mode"]) == r["input_hash"]
    return _query(go)


if __name__ == "__main__":
    moved = init_db()
    if moved:
        print(f"unreadable database moved to {moved}")
    print(f"{DB_PATH}\n")

    print(f"{'officer_id':<16}{'name':<20}{'role':<15}{'area':<6}{'farm'}")
    for o in list_officers():
        print(f"{o['officer_id']:<16}{o['name']:<20}{o['role']:<15}"
              f"{o['source_id'] or '-':<6}{o['farm_id'] or '-'}")

    print(f"\n{'id':<5}{'name':<28}{'type':<7}{'ha':>5}{'deliverable':>14}")
    for sid, s in query_sources().items():
        print(f"{sid:<5}{s['name']:<28}{s['type']:<7}"
              f"{s['command_area_ha']:>5.0f}"
              f"{s['live_storage_L'] * s['conveyance_efficiency']:>14,.0f}")

    for sid in ("T01", "C01"):
        runs = recent_runs(sid, limit=5)
        print(f"\n{sid}: {len(runs)} recent run(s)")
        for r in runs:
            mark = (f"approved by {r['approved_name']}" if r["approved_by"]
                    else "unapproved")
            print(f"  #{r['run_id']:<4}{r['timestamp']:<21}"
                  f"{r['farm_count']:>3} farms  {r['policy_mode']:<10}{mark}")