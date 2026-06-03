import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversation_episodes (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    agent_role TEXT NOT NULL,
    pr_spec TEXT,
    started_at REAL NOT NULL,
    ended_at REAL
);

CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL REFERENCES conversation_episodes(id),
    role TEXT NOT NULL,
    content TEXT,
    timestamp REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
    content,
    content=transcripts,
    content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS transcripts_fts_insert AFTER INSERT ON transcripts BEGIN
    INSERT INTO transcripts_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS transcripts_fts_delete AFTER DELETE ON transcripts BEGIN
    INSERT INTO transcripts_fts(transcripts_fts, rowid, content)
    VALUES('delete', old.id, old.content);
END;
"""


class EdgeMemoryDB:
    """
    SQLite-backed state persistence for the Selva conversational hive mind.
    Utilizes WAL mode and FTS5 for sub-millisecond semantic transcript retrieval.
    """

    def __init__(self, db_path: str = "selva_state.db"):
        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self):
        try:
            self._conn.executescript(SCHEMA_SQL)
        except Exception as e:
            logger.error(f"Failed to initialize SQLite FTS5 Schema: {e}")

    def fts_search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Executes a Full-Text Search against all historical swarms and ACP operators.
        """
        sql = """
            SELECT t.id, t.role, t.content, t.timestamp, e.run_id, e.agent_role
            FROM transcripts_fts fts
            JOIN transcripts t ON fts.rowid = t.id
            JOIN conversation_episodes e ON t.episode_id = e.id
            WHERE transcripts_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        cursor = self._conn.execute(sql, (query, limit))
        return [dict(row) for row in cursor.fetchall()]

    def insert_transcript(self, run_id: str, agent_role: str, role: str, content: str):
        """
        Logs workflow transcripts into the FTS database in real-time, matching
        the persistent episodic memory architecture of Hermes.
        """
        import time
        import uuid

        # Verify or spin up the episode id first to conform with FK constraint
        cursor = self._conn.execute(
            "SELECT id FROM conversation_episodes WHERE run_id = ?",
            (run_id,),
        )
        row = cursor.fetchone()

        if not row:
            episode_id = f"ep-{uuid.uuid4().hex[:8]}"
            self._conn.execute(
                "INSERT INTO conversation_episodes"
                " (id, run_id, agent_role, started_at)"
                " VALUES (?, ?, ?, ?)",
                (episode_id, run_id, agent_role, time.time()),
            )
        else:
            episode_id = row["id"]

        self._conn.execute(
            "INSERT INTO transcripts (episode_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (episode_id, role, content, time.time()),
        )

    def close(self):
        if self._conn:
            self._conn.close()


# Singleton
memory_store = EdgeMemoryDB()
