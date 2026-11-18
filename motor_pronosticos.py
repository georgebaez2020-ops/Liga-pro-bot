"""Motor conservador de pronosticos para Czech Liga Pro.

El modelo usa Elo cronologico aprendido de resultados completos y reciprocos.
No usa datos posteriores al momento de prediccion, cuotas ni supuestos psicologicos.
La probabilidad es una estimacion exploratoria hasta superar backtesting y calibracion.
"""
from __future__ import annotations

import unicodedata
from collections import defaultdict
from datetime import datetime, timezone

from perfil_jugadores import extraer_partidos_historicos


def _key(name):
    return unicodedata.normalize("NFKC", " ".join(str(name or "").split())).casefold()


def _date(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None



def construir_ratings_elo(snapshots, k_factor=24.0, initial_rating=1500.0):
    """Aprende Elo en orden temporal usando solo marcadores finales verificados."""
    matches = extraer_partidos_historicos(snapshots)
    ratings = defaultdict(lambda: float(initial_rating))
    counts = defaultdict(int)
    last_seen = {}
    timeline = []
    for match in matches:
        a, b = _key(match["jugador_a"]), _key(match["jugador_b"])
        if not a or not b or a == b:
            continue
        ra, rb = ratings[a], ratings[b]
        expected_a = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        actual_a = 1.0 if match["sets_a"] > match["sets_b"] else 0.0
        change = k_factor * (actual_a - expected_a)
        ratings[a] += change
        ratings[b] -= change
        counts[a] += 1
        counts[b] += 1
        captured = match.get("fecha_captura")
        last_seen[a] = captured
        last_seen[b] = captured
        timeline.append({
            "fecha": captured, "jugador_a": a, "jugador_b": b,
            "ganador": a if actual_a else b,
            "rating_a_pre": round(ra, 2), "rating_b_pre": round(rb, 2),
        })
    return {
        "ratings": dict(ratings), "partidos": dict(counts),
        "ultima_observacion": last_seen, "timeline": timeline,
        "partidos_validos": len(timeline),
    }


def _h2h_before(matches, a_key, b_key, before=None):
    rows = []
    cutoff = _date(before) if before else None
    for m in matches:
        if {_key(m["jugador_a"]), _key(m["jugador_b"])} != {a_key, b_key}:
            continue
        dt = _date(m.get("fecha_captura"))
        if cutoff and dt and dt >= cutoff:
            continue
        winner = _key(m["jugador_a"]) if m["sets_a"] > m["sets_b"] else _key(m["jugador_b"])
        rows.append((dt, winner))
    return rows


def _sample_confidence(n_a, n_b, h2h_n, stale_days=None):
    total = min(n_a, n_b)
    if total < 5:
        level = "muy_baja"
    elif total < 10:
        level = "baja"
    elif total < 20:
        level = "media"
    else:
        level = "alta"
    score = min(1.0, total / 20.0)
    if h2h_n:
        score = min(1.0, score + min(0.10, h2h_n * 0.02))
    if stale_days is not None:
        if stale_days > 90:
            score *= 0.55
        elif stale_days > 30:
            score *= 0.75
    return level, round(score, 3)


def pronosticar_partido(snapshots, jugador_a, jugador_b, fecha_partido=None,
                        estado="upcoming", minimo_partidos=5):
    """Devuelve pronostico o abstencion explicita para un duelo no iniciado."""
    a_name, b_name = str(jugador_a or "").strip(), str(jugador_b or "").strip()
    a, b = _key(a_name), _key(b_name)
    if not a or not b or a == b:
        return {"elegible": False, "motivo": "jugadores_invalidos"}
    if str(estado).casefold() not in {"planned", "upcoming"}:
        return {"elegible": False, "motivo": "solo_partidos_no_iniciados"}
    matches = extraer_partidos_historicos(snapshots)
    cutoff = _date(fecha_partido)
    if cutoff is None:
        return {"elegible": False, "motivo": "fecha_partido_con_zona_horaria_requerida"}
    matches = [
        m for m in matches
        if _date(m.get("fecha_captura")) is not None
        and _date(m.get("fecha_captura")) < cutoff
    ]
    # Entrenamiento temporal directo: solo resultados observados antes del corte.
    ratings = defaultdict(lambda: 1500.0)
    counts = defaultdict(int)
    for m in matches:
        ka, kb = _key(m["jugador_a"]), _key(m["jugador_b"])
        ra, rb = ratings[ka], ratings[kb]
        expected = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        actual = 1.0 if m["sets_a"] > m["sets_b"] else 0.0
        delta = 24.0 * (actual - expected)
        ratings[ka] += delta
        ratings[kb] -= delta
        counts[ka] += 1
        counts[kb] += 1
    n_a, n_b = counts[a], counts[b]
    h2h = _h2h_before(matches, a, b)
    recent = {a: [], b: []}
    for match in matches:
        ka, kb = _key(match["jugador_a"]), _key(match["jugador_b"])
        if ka in recent:
            recent[ka].append(1.0 if match["sets_a"] > match["sets_b"] else 0.0)
        if kb in recent:
            recent[kb].append(1.0 if match["sets_b"] > match["sets_a"] else 0.0)
    form_a_rows, form_b_rows = recent[a][-10:], recent[b][-10:]
    form_a = sum(form_a_rows) / len(form_a_rows) if form_a_rows else 0.5
    form_b = sum(form_b_rows) / len(form_b_rows) if form_b_rows else 0.5
    if min(n_a, n_b) < minimo_partidos:
        return {
            "elegible": False, "motivo": "muestra_historica_insuficiente",
            "partidos_historicos_a": n_a, "partidos_historicos_b": n_b,
            "minimo_requerido_por_jugador": minimo_partidos,
        }
    elo_a, elo_b = ratings[a], ratings[b]
    raw = 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))
    # H2H tiene peso pequeno y se contrae hacia 50%; no domina el Elo.
    h2h_n = len(h2h)
    h2h_wins_a = sum(1 for _, winner in h2h if winner == a)
    h2h_rate = (h2h_wins_a + 2.0) / (h2h_n + 4.0)
    h2h_weight = min(0.08, h2h_n / 50.0)
    probability_a = (1.0 - h2h_weight) * raw + h2h_weight * h2h_rate
    # Forma reciente (ultimos 10 resultados previos al corte): peso maximo 10%,
    # reducido proporcionalmente si la muestra de cualquiera es menor de 10.
    form_weight = 0.10 * min(1.0, len(form_a_rows) / 10.0, len(form_b_rows) / 10.0)
    form_signal = 0.5 + (form_a - form_b) / 2.0
    probability_a = (1.0 - form_weight) * probability_a + form_weight * form_signal
    # La contraccion evita extremos cuando hay poca experiencia individual.
    experience = min(1.0, min(n_a, n_b) / 20.0)
    probability_a = 0.5 + (probability_a - 0.5) * (0.55 + 0.45 * experience)
    probability_a = max(0.05, min(0.95, probability_a))
    level, confidence = _sample_confidence(n_a, n_b, h2h_n)
    if confidence < 0.35:
        return {
            "elegible": False, "motivo": "confianza_insuficiente",
            "confianza_muestra": confidence, "nivel_confianza": level,
        }
    pa = round(probability_a * 100, 1)
    pb = round(100.0 - pa, 1)
    return {
        "elegible": True, "jugador_a": a_name, "jugador_b": b_name,
        "probabilidad_a": pa, "probabilidad_b": pb,
        "favorito": a_name if pa > 50 else b_name if pb > 50 else None,
        "diferencia_elo": round(elo_a - elo_b, 1),
        "rating_elo_a": round(elo_a, 1), "rating_elo_b": round(elo_b, 1),
        "partidos_historicos_a": n_a, "partidos_historicos_b": n_b,
        "h2h_partidos": h2h_n, "h2h_victorias_a": h2h_wins_a,
        "forma_ultimos_10_a": {"partidos": len(form_a_rows), "victorias": int(sum(form_a_rows)), "tasa": round(form_a, 3) if form_a_rows else None},
        "forma_ultimos_10_b": {"partidos": len(form_b_rows), "victorias": int(sum(form_b_rows)), "tasa": round(form_b, 3) if form_b_rows else None},
        "peso_forma_reciente": round(form_weight, 3),
        "nivel_confianza": level, "confianza_muestra": confidence,
        "metodo": "Elo cronologico + H2H contraido + forma reciente (max 10%) + contraccion por experiencia",
        "advertencia": "Probabilidad exploratoria; no calibrada ni validada aun con backtesting fuera de muestra.",
    }


def pronosticar_calendario(snapshots, partidos, minimo_partidos=5):
    """Pronostica solo tarjetas planned/upcoming; conserva abstenciones."""
    output = []
    for match in partidos or []:
        status = str(match.get("estado") or match.get("status") or "").casefold()
        if status not in {"planned", "upcoming"}:
            continue
        result = pronosticar_partido(
            snapshots, match.get("jugador_a"), match.get("jugador_b"),
            fecha_partido=match.get("fecha") or match.get("scheduled_at"), estado=status,
            minimo_partidos=minimo_partidos,
        )
        output.append({
            "partido": match, "pronostico": result,
            "id_partido": match.get("id") or match.get("partido_id"),
        })
    return output
