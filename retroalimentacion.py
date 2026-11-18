"""Registro y evaluación continua de pronósticos, sin aprendizaje con datos futuros.

El módulo persiste predicciones antes del partido y las liquida únicamente cuando
el scraper confirma un marcador final. Las métricas evalúan el modelo; no cambian
automáticamente sus parámetros.
"""
from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from datetime import datetime, timezone

from perfil_jugadores import extraer_partidos_historicos


def _key(value):
    return unicodedata.normalize("NFKC", " ".join(str(value or "").split())).casefold()


def _stamp(value=None):
    if value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Las fechas deben incluir zona horaria.")
        return parsed.astimezone(timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _prediction_id(match):
    parts = [
        str(match.get("torneo_id") or match.get("tournament_id") or ""),
        str(match.get("grupo") or match.get("group_number") or ""),
        _key(match.get("jugador_a")), _key(match.get("jugador_b")),
        str(match.get("fecha") or match.get("scheduled_at") or ""),
    ]
    if not all(parts[:4]):
        raise ValueError("Faltan torneo, grupo o jugadores para identificar el partido.")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


class PredictionFeedback:
    """Almacena predicciones y resultados en la misma DB histórica."""

    def __init__(self, db):
        self.db = db
        self._initialize()

    def _initialize(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS predictions (
                prediction_id TEXT PRIMARY KEY,
                tournament_id TEXT NOT NULL,
                group_number TEXT,
                player_a TEXT NOT NULL,
                player_b TEXT NOT NULL,
                scheduled_at TEXT,
                predicted_at TEXT NOT NULL,
                model_version TEXT NOT NULL,
                probability_a REAL NOT NULL,
                probability_b REAL NOT NULL,
                confidence REAL,
                forecast_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                actual_winner TEXT,
                actual_score TEXT,
                settled_at TEXT
            )""",
            "CREATE INDEX IF NOT EXISTS idx_predictions_status ON predictions(status)",
            "CREATE INDEX IF NOT EXISTS idx_predictions_model ON predictions(model_version, status)",
        ]
        with self.db._connect() as conn:
            cur = conn.cursor()
            for sql in statements:
                self.db._execute(cur, sql)

    def record(self, match, forecast, predicted_at=None, model_version="elo-h2h-v1"):
        if not forecast or not forecast.get("elegible"):
            return None
        pa = float(forecast["probabilidad_a"]) / 100.0
        pb = float(forecast["probabilidad_b"]) / 100.0
        if not (0 < pa < 1 and 0 < pb < 1) or abs(pa + pb - 1.0) > 0.002:
            raise ValueError("Probabilidades inválidas: deben sumar 100% y estar entre 0 y 100.")
        row = {
            "prediction_id": _prediction_id(match),
            "tournament_id": str(match.get("torneo_id") or match.get("tournament_id")),
            "group_number": str(match.get("grupo") or match.get("group_number") or ""),
            "player_a": str(forecast.get("jugador_a") or match.get("jugador_a")),
            "player_b": str(forecast.get("jugador_b") or match.get("jugador_b")),
            "scheduled_at": match.get("fecha") or match.get("scheduled_at"),
            "predicted_at": _stamp(predicted_at),
            "model_version": str(model_version),
            "probability_a": pa, "probability_b": pb,
            "confidence": forecast.get("confianza_muestra"),
            "forecast_json": json.dumps(forecast, ensure_ascii=False, default=str),
        }
        sql = """INSERT INTO predictions
            (prediction_id,tournament_id,group_number,player_a,player_b,scheduled_at,
             predicted_at,model_version,probability_a,probability_b,confidence,forecast_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(prediction_id) DO NOTHING"""
        with self.db._connect() as conn:
            self.db._execute(conn.cursor(), sql, tuple(row.values()))
        return row["prediction_id"]

    def settle_from_snapshots(self, snapshots):
        """Liquida pendientes con marcadores completos y recíprocos confirmados."""
        matches = extraer_partidos_historicos(snapshots)
        settled = 0
        with self.db._connect() as conn:
            cur = conn.cursor()
            self.db._execute(cur, """SELECT prediction_id,tournament_id,group_number,
                player_a,player_b,predicted_at FROM predictions WHERE status='pending'""")
            pending = cur.fetchall()
            for pid, tid, group_no, player_a, player_b, predicted_at in pending:
                a, b = _key(player_a), _key(player_b)
                candidates = [
                    m for m in matches
                    if str(m["torneo_id"]) == str(tid)
                    and str(m["grupo"]) == str(group_no)
                    and {_key(m["jugador_a"]), _key(m["jugador_b"])} == {a, b}
                    and _stamp(m.get("fecha_captura")) > predicted_at
                ]
                if not candidates:
                    continue
                result = candidates[0]
                winner = _key(result["jugador_a"]) if result["sets_a"] > result["sets_b"] else _key(result["jugador_b"])
                score = (result["sets_a"], result["sets_b"])
                if _key(result["jugador_a"]) != a:
                    score = score[::-1]
                self.db._execute(cur, """UPDATE predictions SET status='settled',
                    actual_winner=?,actual_score=?,settled_at=? WHERE prediction_id=? AND status='pending'""",
                    (player_a if winner == a else player_b, f"{score[0]}:{score[1]}",
                     _stamp(result.get("fecha_captura")), pid))
                settled += 1
        return {"liquidados": settled, "pendientes_revisados": len(pending)}

    def metrics(self, model_version=None):
        where = "WHERE status='settled'"
        params = ()
        if model_version:
            where += " AND model_version=?"
            params = (model_version,)
        with self.db._connect() as conn:
            cur = conn.cursor()
            self.db._execute(cur, f"""SELECT probability_a,player_a,actual_winner
                FROM predictions {where}""", params)
            rows = cur.fetchall()
        if not rows:
            return {"muestra": 0, "estado": "sin_resultados_liquidados"}
        brier = logloss = correct = 0.0
        eps = 1e-15
        for probability_a, player_a, winner in rows:
            actual = 1.0 if _key(player_a) == _key(winner) else 0.0
            p = min(1 - eps, max(eps, float(probability_a)))
            brier += (p - actual) ** 2
            logloss -= actual * math.log(p) + (1 - actual) * math.log(1 - p)
            correct += int((p >= 0.5) == bool(actual))
        n = len(rows)
        return {
            "muestra": n, "accuracy": round(correct / n, 4),
            "brier": round(brier / n, 5), "log_loss": round(logloss / n, 5),
            "estado": "evaluacion_descriptiva_no_calibrada",
            "nota": "No ajustar parámetros sin backtesting cronológico y muestra suficiente.",
        }
