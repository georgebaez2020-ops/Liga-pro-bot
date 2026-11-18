"""Persistencia historica para Liga Pro Bot (PostgreSQL en Render / SQLite local)."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = [
    """CREATE TABLE IF NOT EXISTS tournaments (
        tournament_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        listing_text TEXT,
        listing_class TEXT,
        scrape_day_colombia TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        latest_payload TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS tournament_snapshots (
        tournament_id TEXT NOT NULL,
        captured_at TEXT NOT NULL,
        status TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (tournament_id, captured_at)
    )""",
    """CREATE TABLE IF NOT EXISTS players (
        player_key TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS tournament_players (
        tournament_id TEXT NOT NULL,
        group_number INTEGER NOT NULL,
        player_key TEXT NOT NULL,
        position TEXT,
        rating TEXT,
        results_json TEXT NOT NULL,
        sets_value TEXT,
        balls_value TEXT,
        points_value TEXT,
        place_value TEXT,
        captured_at TEXT NOT NULL,
        PRIMARY KEY (tournament_id, group_number, player_key)
    )""",
    """CREATE TABLE IF NOT EXISTS matches (
        tournament_id TEXT NOT NULL,
        group_number INTEGER NOT NULL,
        player_a_key TEXT NOT NULL,
        player_b_key TEXT NOT NULL,
        score_a INTEGER NOT NULL,
        score_b INTEGER NOT NULL,
        captured_at TEXT NOT NULL,
        PRIMARY KEY (tournament_id, group_number, player_a_key, player_b_key)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_matches_players ON matches (player_a_key, player_b_key)",
    "CREATE INDEX IF NOT EXISTS idx_tournaments_status ON tournaments (status)",
]


def _player_key(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", " ".join(name.split()))
    return normalized.casefold()


def _score(value: Any):
    match = re.fullmatch(r"\s*(\d+)\s*:\s*(\d+)\s*", str(value or ""))
    if not match:
        return None
    a, b = map(int, match.groups())
    return (a, b) if a != b else None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class HistoryDB:
    """Usa DATABASE_URL si existe; de lo contrario crea SQLite local para pruebas."""

    def __init__(self, database_url: str | None = None, sqlite_path: str | None = None):
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self.sqlite_path = sqlite_path or os.getenv("DB_PATH", "salida/liga_pro.db")
        self.kind = "postgres" if self.database_url else "sqlite"

    def _connect(self):
        if self.kind == "postgres":
            try:
                import psycopg
            except ImportError as exc:
                raise RuntimeError("Falta instalar psycopg[binary] para PostgreSQL") from exc
            url = self.database_url
            if url.startswith("postgres://"):
                url = "postgresql://" + url[len("postgres://"):]
            return psycopg.connect(url)
        Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.sqlite_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _execute(self, cursor, sql: str, params=()):
        if self.kind == "postgres":
            sql = sql.replace("?", "%s")
        cursor.execute(sql, params)

    def initialize(self):
        with self._connect() as conn:
            cur = conn.cursor()
            for statement in SCHEMA:
                self._execute(cur, statement)
        return self.kind

    def listar_snapshots(self) -> list[dict[str, Any]]:
        """Devuelve snapshots cronológicos para análisis de evolución entre capturas."""
        self.initialize()
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""SELECT tournament_id, captured_at, status, payload
                FROM tournament_snapshots ORDER BY captured_at ASC, tournament_id ASC""")
            rows = cur.fetchall()
        return [
            {
                "tournament_id": str(row[0]),
                "captured_at": str(row[1]),
                "status": str(row[2]),
                "payload": json.loads(row[3]) if isinstance(row[3], str) else row[3],
            }
            for row in rows
        ]

    def save_scrape(self, data: dict[str, Any]) -> dict[str, int]:
        """Guarda estado actual y snapshots; solo promueve marcadores recíprocos completos."""
        self.initialize()
        generated = str(data.get("generado") or datetime.now(timezone.utc).isoformat())
        scrape_day = data.get("dia_colombia")
        counts = {"torneos": 0, "snapshots": 0, "jugadores": 0,
                  "participaciones": 0, "partidos_validos": 0}
        with self._connect() as conn:
            cur = conn.cursor()
            for tid, tournament in data.get("torneos", {}).items():
                tid = str(tid)
                status = str(tournament.get("estado") or "unknown")
                payload = _json(tournament)
                listing = tournament.get("texto_listado")
                listing_class = tournament.get("clase_tarjeta")
                self._execute(cur, """INSERT INTO tournaments
                    (tournament_id,status,listing_text,listing_class,scrape_day_colombia,
                     first_seen_at,last_seen_at,latest_payload)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(tournament_id) DO UPDATE SET
                    status=excluded.status, listing_text=excluded.listing_text,
                    listing_class=excluded.listing_class,
                    scrape_day_colombia=excluded.scrape_day_colombia,
                    last_seen_at=excluded.last_seen_at, latest_payload=excluded.latest_payload""",
                    (tid,status,listing,listing_class,scrape_day,generated,generated,payload))
                counts["torneos"] += 1

                self._execute(cur, """INSERT INTO tournament_snapshots
                    (tournament_id,captured_at,status,payload) VALUES (?,?,?,?)
                    ON CONFLICT(tournament_id,captured_at) DO NOTHING""",
                    (tid,generated,status,payload))
                counts["snapshots"] += 1

                for group_no, group in enumerate(tournament.get("grupos", []), start=1):
                    names = [str(p.get("jugador") or "").strip() for p in group]
                    keys = [_player_key(n) if n else "" for n in names]
                    for p, name, key in zip(group, names, keys):
                        if not name or not key:
                            continue
                        self._execute(cur, """INSERT INTO players
                            (player_key,display_name,first_seen_at,last_seen_at)
                            VALUES (?,?,?,?) ON CONFLICT(player_key) DO UPDATE SET
                            display_name=excluded.display_name,last_seen_at=excluded.last_seen_at""",
                            (key,name,generated,generated))
                        counts["jugadores"] += 1
                        self._execute(cur, """INSERT INTO tournament_players
                            (tournament_id,group_number,player_key,position,rating,results_json,
                             sets_value,balls_value,points_value,place_value,captured_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(tournament_id,group_number,player_key) DO UPDATE SET
                            position=excluded.position,rating=excluded.rating,
                            results_json=excluded.results_json,sets_value=excluded.sets_value,
                            balls_value=excluded.balls_value,points_value=excluded.points_value,
                            place_value=excluded.place_value,captured_at=excluded.captured_at""",
                            (tid,group_no,key,p.get("pos"),p.get("rating"),_json(p.get("resultados",[])),
                             p.get("sets"),p.get("balls"),p.get("points"),p.get("place"),generated))
                        counts["participaciones"] += 1

                    for i, p in enumerate(group):
                        for j in range(i + 1, len(group)):
                            if not keys[i] or not keys[j]:
                                continue
                            results_a = p.get("resultados", [])
                            results_b = group[j].get("resultados", [])
                            raw_a = results_a[j] if j < len(results_a) else ""
                            raw_b = results_b[i] if i < len(results_b) else ""
                            score_a, score_b = _score(raw_a), _score(raw_b)
                            if not score_a or not score_b:
                                continue
                            if score_a != (score_b[1], score_b[0]):
                                continue
                            a_key, b_key = sorted((keys[i], keys[j]))
                            a_score = score_a if keys[i] == a_key else score_b
                            self._execute(cur, """INSERT INTO matches
                                (tournament_id,group_number,player_a_key,player_b_key,
                                 score_a,score_b,captured_at) VALUES (?,?,?,?,?,?,?)
                                ON CONFLICT(tournament_id,group_number,player_a_key,player_b_key)
                                DO UPDATE SET score_a=excluded.score_a,score_b=excluded.score_b,
                                captured_at=excluded.captured_at""",
                                (tid,group_no,a_key,b_key,a_score[0],a_score[1],generated))
                            counts["partidos_validos"] += 1
        return counts


def save_scrape_file(path: str = "salida/tablas.json") -> dict[str, int]:
    with open(path, encoding="utf-8") as source:
        data = json.load(source)
    return HistoryDB().save_scrape(data)
