"""SQLite store for the provenance log.

Records are sources; events are append-only moves of a record through the
stages for one strand; codes are coded study attributes (genre, sample, ...).
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from zotero_mcp.provenance import ACTORS, EVIDENCE, ROUTES, STAGES

_SCHEMA = """
CREATE TABLE IF NOT EXISTS record (
    id INTEGER PRIMARY KEY,
    first_author TEXT NOT NULL,
    authors TEXT NOT NULL,
    year TEXT NOT NULL,
    match_key TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    zotero_key TEXT UNIQUE,
    doi TEXT UNIQUE,
    raw TEXT NOT NULL DEFAULT '',
    needs_check INTEGER NOT NULL DEFAULT 0,
    retroactive INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS record_match ON record(match_key);
CREATE TABLE IF NOT EXISTS event (
    id INTEGER PRIMARY KEY,
    record_id INTEGER NOT NULL REFERENCES record(id),
    strand TEXT NOT NULL,
    stage TEXT NOT NULL,
    decision TEXT NOT NULL DEFAULT 'keep',
    reason TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT 'metadata',
    actor TEXT NOT NULL DEFAULT 'assistant',
    client TEXT NOT NULL DEFAULT '',
    reader TEXT NOT NULL DEFAULT '',
    what_read TEXT NOT NULL DEFAULT '',
    route TEXT NOT NULL DEFAULT '',
    source_ref TEXT NOT NULL DEFAULT '',
    confirmation TEXT NOT NULL DEFAULT '',
    supersedes INTEGER REFERENCES event(id),
    dedupe_key TEXT UNIQUE,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS event_strand ON event(strand, record_id);
CREATE TABLE IF NOT EXISTS code (
    id INTEGER PRIMARY KEY,
    record_id INTEGER NOT NULL REFERENCES record(id),
    field TEXT NOT NULL,
    value TEXT NOT NULL,
    evidence TEXT NOT NULL,
    locator TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT 'assistant',
    client TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9&]+", " ", s.lower()).strip()


def match_key(authors: str, year: str) -> str:
    """Normalized author string + year, e.g. 'darragh & boyd|2019'."""
    a = _fold(authors).replace(" and ", " & ")
    a = re.sub(r"\bet al\b", "et al", a)
    return f"{a}|{year.strip().lower()}"


def _check(value: str, allowed: tuple[str, ...], name: str) -> None:
    if value not in allowed:
        raise ValueError(f"Unknown {name} {value!r}; expected one of {', '.join(allowed)}")


class ProvenanceStore:
    def __init__(self, path: str | Path):
        path = str(path)
        if path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
            path = str(Path(path).expanduser())
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # -- records -----------------------------------------------------------
    def upsert_record(
        self,
        *,
        first_author: str,
        year: str,
        authors: str,
        title: str = "",
        zotero_key: str | None = None,
        doi: str | None = None,
        raw: str = "",
        needs_check: bool = False,
        retroactive: bool = False,
    ) -> int:
        doi = doi.strip().lower() if doi else None
        mk = match_key(authors or first_author, year)
        row = None
        if zotero_key:
            row = self._db.execute("SELECT * FROM record WHERE zotero_key=?", (zotero_key,)).fetchone()
        if row is None and doi:
            row = self._db.execute("SELECT * FROM record WHERE doi=?", (doi,)).fetchone()
        if row is None:
            row = self._db.execute("SELECT * FROM record WHERE match_key=?", (mk,)).fetchone()
        if row is None:
            cur = self._db.execute(
                "INSERT INTO record(first_author,authors,year,match_key,title,zotero_key,doi,raw,"
                "needs_check,retroactive,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (first_author, authors or first_author, year, mk, title, zotero_key, doi, raw,
                 int(needs_check), int(retroactive), _now()),
            )
            self._db.commit()
            return int(cur.lastrowid)
        updates: dict[str, object] = {}
        for col, val in (("title", title), ("zotero_key", zotero_key), ("doi", doi), ("raw", raw)):
            if val and not row[col]:
                updates[col] = val
        if retroactive and not row["retroactive"]:
            updates["retroactive"] = 1
        if zotero_key and row["needs_check"] and not needs_check:
            updates["needs_check"] = 0  # matched to Zotero now
        if updates:
            sets = ", ".join(f"{k}=?" for k in updates)
            self._db.execute(f"UPDATE record SET {sets} WHERE id=?", (*updates.values(), row["id"]))
            self._db.commit()
        return int(row["id"])

    def set_needs_check(self, record_id: int, value: bool) -> None:
        self._db.execute("UPDATE record SET needs_check=? WHERE id=?", (int(value), record_id))
        self._db.commit()

    def record(self, record_id: int) -> dict:
        row = self._db.execute("SELECT * FROM record WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(f"No record {record_id}")
        return dict(row)

    def find(self, first_author: str, year: str) -> list[dict]:
        fa = _fold(first_author)
        rows = self._db.execute("SELECT * FROM record WHERE year=?", (year,)).fetchall()
        return [dict(r) for r in rows if _fold(r["first_author"]) == fa]

    def find_by_zotero_key(self, key: str) -> dict | None:
        row = self._db.execute("SELECT * FROM record WHERE zotero_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def records(self) -> list[dict]:
        return [dict(r) for r in self._db.execute("SELECT * FROM record ORDER BY id")]

    # -- events ------------------------------------------------------------
    def add_event(
        self,
        record_id: int,
        *,
        strand: str,
        stage: str,
        decision: str = "keep",
        reason: str = "",
        note: str = "",
        evidence: str = "metadata",
        actor: str = "assistant",
        client: str = "",
        reader: str = "",
        what_read: str = "",
        route: str = "",
        source_ref: str = "",
        confirmation: str = "",
        supersedes: int | None = None,
        dedupe_key: str | None = None,
    ) -> int | None:
        _check(stage, STAGES, "stage")
        _check(evidence, EVIDENCE, "evidence level")
        _check(actor, ACTORS, "actor")
        _check(decision, ("keep", "exclude"), "decision")
        if route:
            _check(route, ROUTES, "route")
        if not strand.strip():
            raise ValueError("strand is required")
        self.record(record_id)  # raises KeyError if missing
        try:
            cur = self._db.execute(
                "INSERT INTO event(record_id,strand,stage,decision,reason,note,evidence,actor,client,"
                "reader,what_read,route,source_ref,confirmation,supersedes,dedupe_key,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (record_id, strand, stage, decision, reason, note, evidence, actor, client, reader,
                 what_read, route, source_ref, confirmation, supersedes, dedupe_key, _now()),
            )
        except sqlite3.IntegrityError:
            if dedupe_key and self._db.execute(
                "SELECT 1 FROM event WHERE dedupe_key=?", (dedupe_key,)
            ).fetchone():
                return None
            raise
        self._db.commit()
        return int(cur.lastrowid)

    def events(self, strand: str | None = None) -> list[dict]:
        if strand is None:
            rows = self._db.execute("SELECT * FROM event ORDER BY id")
        else:
            rows = self._db.execute("SELECT * FROM event WHERE strand=? ORDER BY id", (strand,))
        return [dict(r) for r in rows]

    # -- codes -------------------------------------------------------------
    def add_code(
        self,
        record_id: int,
        *,
        field: str,
        value: str,
        evidence: str,
        locator: str = "",
        actor: str = "assistant",
        client: str = "",
    ) -> int:
        _check(evidence, EVIDENCE, "evidence level")
        _check(actor, ACTORS, "actor")
        self.record(record_id)
        cur = self._db.execute(
            "INSERT INTO code(record_id,field,value,evidence,locator,actor,client,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (record_id, field, value, evidence, locator, actor, client, _now()),
        )
        self._db.commit()
        return int(cur.lastrowid)

    def codes(self, record_id: int | None = None) -> list[dict]:
        if record_id is None:
            rows = self._db.execute("SELECT * FROM code ORDER BY id")
        else:
            rows = self._db.execute("SELECT * FROM code WHERE record_id=? ORDER BY id", (record_id,))
        return [dict(r) for r in rows]

    def trail(self, record_id: int) -> dict:
        rec = self.record(record_id)
        ev = [dict(r) for r in self._db.execute(
            "SELECT * FROM event WHERE record_id=? ORDER BY id", (record_id,))]
        return {"record": rec, "events": ev, "codes": self.codes(record_id)}
