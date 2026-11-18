"""Reconstrucción cronológica de torneos desde el calendario oficial de partidos.

La fuente debe aportar partidos ordenados (hora/orden), marcador de sets y
rating +/- publicado por la sección Players. No se inventan partidos ni puntos.
"""
from __future__ import annotations

from itertools import combinations, product


def _score(value):
    if isinstance(value, (tuple, list)) and len(value) == 2:
        a, b = value
    else:
        import re
        m = re.fullmatch(r"\s*(\d+)\s*[:\-]\s*(\d+)\s*", str(value or ""))
        if not m:
            return None
        a, b = map(int, m.groups())
    a, b = int(a), int(b)
    return (a, b) if a != b else None


def _best_place(points, pending, player):
    names = list(points)
    best = len(names)
    for outcomes in product((0, 1), repeat=len(pending)):
        totals = dict(points)
        for (a, b), winner in zip(pending, outcomes):
            win, lose = (a, b) if winner == 0 else (b, a)
            totals[win] += 2
            totals[lose] += 1
        best = min(best, 1 + sum(v > totals[player] for v in totals.values()))
    return best


def reconstruir_secuencia(jugadores, partidos, rating_torneo=None):
    """Reconstruye la tabla antes y después de cada partido, en orden de fuente.

    jugadores: nombres exactos del grupo.
    partidos: [{jugador_a, jugador_b, marcador_sets, hora?, orden?}]
    rating_torneo: {nombre: {rating_final, variacion}} desde Players.
    """
    names = [str(x).strip() for x in jugadores]
    if len(names) not in (4, 5) or len(set(names)) != len(names):
        raise ValueError("Se requieren 4 o 5 jugadores con nombres únicos")
    known = set(names)
    played = set()
    points = {n: 0 for n in names}
    wins = {n: 0 for n in names}
    losses = {n: 0 for n in names}
    sets_for = {n: 0 for n in names}
    sets_against = {n: 0 for n in names}
    sequence, warnings = [], []
    normalized = []

    for idx, match in enumerate(partidos):
        a, b = str(match.get("jugador_a") or "").strip(), str(match.get("jugador_b") or "").strip()
        score = _score(match.get("marcador_sets"))
        if a not in known or b not in known or a == b or score is None:
            warnings.append({"indice": idx, "motivo": "partido incompleto o jugadores no identificados"})
            continue
        pair = frozenset((a, b))
        if pair in played:
            warnings.append({"indice": idx, "motivo": "partido duplicado"})
            continue
        if max(score) > 3 or min(score) > 2:
            warnings.append({"indice": idx, "motivo": "marcador de sets fuera del formato esperado"})
            continue
        played.add(pair)
        normalized.append((match, a, b, score))

    for idx, (match, a, b, score) in enumerate(normalized):
        remaining = [(x, y) for x, y in combinations(names, 2)
                     if frozenset((x, y)) not in played or
                     (frozenset((x, y)) == frozenset((a, b)) and idx < len(normalized))]
        remaining = [(x, y) for x, y in remaining
                     if frozenset((x, y)) != frozenset((a, b))]
        # Se consideran solo duelos aún no disputados en esta secuencia.
        before = {n: points[n] for n in names}
        necessity = {}
        cutoff_phase = 2 if len(names) == 4 else 4
        for player, opponent in ((a, b), (b, a)):
            win_best = _best_place(before, remaining, player)
            lose_points = dict(before)
            lose_points[opponent] += 2
            lose_points[player] += 1
            loss_best = _best_place(lose_points, remaining, player)
            necessity[player] = {
                "debe_ganar_para_seguir_en_fase": win_best <= cutoff_phase and loss_best > cutoff_phase,
                "puede_clasificar_si_pierde": loss_best <= cutoff_phase,
                "mejor_puesto_si_gana": win_best,
                "mejor_puesto_si_pierde": loss_best,
            }

        winner, loser = (a, b) if score[0] > score[1] else (b, a)
        points[winner] += 2
        points[loser] += 1
        wins[winner] += 1
        losses[loser] += 1
        sets_for[a] += score[0]
        sets_against[a] += score[1]
        sets_for[b] += score[1]
        sets_against[b] += score[0]
        result = {
            "orden": match.get("orden", idx + 1),
            "hora": match.get("hora"),
            "jugador_a": a, "jugador_b": b,
            "marcador_sets": f"{score[0]}:{score[1]}",
            "ganador": winner,
            "necesidad_antes": necessity,
            "cumplio_necesidad": {
                a: (winner == a) if necessity[a]["debe_ganar_para_seguir_en_fase"] else None,
                b: (winner == b) if necessity[b]["debe_ganar_para_seguir_en_fase"] else None,
            },
            "tabla_despues": sorted([
                {"jugador": n, "puntos": points[n], "victorias": wins[n],
                 "derrotas": losses[n], "sets_favor": sets_for[n],
                 "sets_contra": sets_against[n],
                 "diferencia_sets": sets_for[n] - sets_against[n]}
                for n in names
            ], key=lambda row: (-row["puntos"], -row["sets_favor"],
                                -row["diferencia_sets"], row["jugador"].casefold())),
        }
        sequence.append(result)

    rating_torneo = rating_torneo or {}
    ratings = {}
    for name in names:
        raw = rating_torneo.get(name) or {}
        try:
            final_rating = float(raw["rating_final"]) if raw.get("rating_final") not in (None, "") else None
        except (TypeError, ValueError):
            final_rating = None
        try:
            delta = float(raw["variacion"]) if raw.get("variacion") not in (None, "") else None
        except (TypeError, ValueError):
            delta = None
        ratings[name] = {
            "rating_final": final_rating,
            "variacion_torneo": delta,
            "rating_inicial_estimado": final_rating - delta if final_rating is not None and delta is not None else None,
            "fuente": "seccion Players de la ficha del torneo",
        }

    return {
        "metodo": "resultados oficiales ordenados por hora; tabla reconstruida tras cada partido",
        "partidos_reconstruidos": len(sequence),
        "partidos_esperados": len(names) * (len(names) - 1) // 2,
        "secuencia": sequence,
        "tabla_final_reconstruida": sequence[-1]["tabla_despues"] if sequence else [],
        "rating_por_jugador": ratings,
        "advertencias": warnings + (["La tabla usa puntos y sets; los desempates oficiales por puntos de juego/H2H no se simulan por partido."] if sequence else []),
        "completa": len(sequence) == len(names) * (len(names) - 1) // 2 and not warnings,
    }
