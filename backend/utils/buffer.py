"""
utils/buffer.py
===============
Thread-safe SQLite offline write buffer.

WHY THIS EXISTS
---------------
The boat operates on the Nile with cellular/WiFi connectivity that can
drop at any moment.  Without this buffer, every Firebase write during a
connection outage is silently lost.

HOW IT WORKS
------------
1. FirebaseManager calls buffer.enqueue(collection, data_dict) for every
   write it wants to make.
2. If Firebase is reachable the manager calls buffer.flush(writer_fn)
   which empties the queue by calling writer_fn(collection, data) for
   each pending row.
3. If Firebase is unreachable the rows stay in SQLite until the next
   flush attempt.
4. The buffer is capped at MAX_ROWS to prevent unbounded disk growth on
   long missions.

Thread safety: SQLite WAL mode + per-connection check_same_thread=False
is safe for the single-writer / single-flusher pattern used here.
"""

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Any, List, Tuple

from utils.logger import get_logger

log = get_logger("buffer")

MAX_ROWS     = 50_000
FLUSH_LIMIT  = 500      # rows per flush call to avoid single huge transaction


class OfflineBuffer:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock    = threading.Lock()
        self._conn    = self._connect()
        self._create_tables()

    # ── internal ─────────────────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            timeout=10,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _create_tables(self) -> None:
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS write_queue (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection  TEXT    NOT NULL,
                    payload     TEXT    NOT NULL,   -- JSON
                    created_at  REAL    NOT NULL,
                    attempts    INTEGER DEFAULT 0
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_created ON write_queue(created_at)"
            )
            self._conn.commit()

    # ── public API ────────────────────────────────────────────────────────────
    def enqueue(self, collection: str, data: Dict[str, Any]) -> None:
        """Add one write to the queue. Caps at MAX_ROWS (drops oldest)."""
        with self._lock:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM write_queue"
            ).fetchone()[0]
            if count >= MAX_ROWS:
                # drop oldest 10 % to make room
                drop = max(1, MAX_ROWS // 10)
                self._conn.execute(
                    "DELETE FROM write_queue WHERE id IN "
                    "(SELECT id FROM write_queue ORDER BY id ASC LIMIT ?)",
                    (drop,),
                )
                log.warning(f"[Buffer] Queue full — dropped {drop} oldest rows")
            self._conn.execute(
                "INSERT INTO write_queue (collection, payload, created_at) VALUES (?, ?, ?)",
                (collection, json.dumps(data), time.time()),
            )
            self._conn.commit()

    def flush(self, writer: Callable[[str, Dict[str, Any]], bool]) -> Tuple[int, int]:
        """
        Call writer(collection, data) for each pending row.
        writer should return True on success, False on failure.
        Returns (success_count, fail_count).
        """
        with self._lock:
            rows: List[sqlite3.Row] = self._conn.execute(
                "SELECT id, collection, payload FROM write_queue "
                "ORDER BY id ASC LIMIT ?",
                (FLUSH_LIMIT,),
            ).fetchall()

        ok = fail = 0
        ids_to_delete = []

        for row_id, collection, payload in rows:
            try:
                data = json.loads(payload)
                success = writer(collection, data)
            except Exception as exc:
                log.error(f"[Buffer] Writer exception: {exc}")
                success = False

            if success:
                ids_to_delete.append(row_id)
                ok += 1
            else:
                fail += 1
                # increment attempt counter but keep the row
                with self._lock:
                    self._conn.execute(
                        "UPDATE write_queue SET attempts = attempts + 1 WHERE id = ?",
                        (row_id,),
                    )

        if ids_to_delete:
            with self._lock:
                placeholders = ",".join("?" * len(ids_to_delete))
                self._conn.execute(
                    f"DELETE FROM write_queue WHERE id IN ({placeholders})",
                    ids_to_delete,
                )
                self._conn.commit()

        if ok or fail:
            log.info(f"[Buffer] Flush: {ok} written, {fail} failed, {self.pending_count()} remaining")
        return ok, fail

    def pending_count(self) -> int:
        with self._lock:
            try:
                return self._conn.execute(
                    "SELECT COUNT(*) FROM write_queue"
                ).fetchone()[0]
            except Exception:
                return 0

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
