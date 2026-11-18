"""Reconstrucción cronológica de torneos desde el calendario oficial de partidos."""
from __future__ import annotations

from itertools import product


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
    names = [str(x).strip() for x in jugadores]
    if len(names) not in (4, 5) or len(set(names)) != len(names):
        raise ValueError("Se requieren 4 o 5 jugadores con nombres únicos")
    known = set(names)
    played, points = set(), {n: 0 for n in names}
    wins, losses = {n: 0 for n in names}, {n: 0 for n in names}
    sets_for, sets_against = {n: 0 for n in names}, {n: 0 for n in names}
    sequence, warnings, normalized = [], [], []

    for idx, match in enumerate(partidos):
        a = str(match.get("jugador_a") or "").strip()
        b = str(match.get("jugador_b") or "").strip()
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
        remaining = [(future[1], future[2]) for future in normalized[idx + 1:]]
        before = dict(points)
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
        sequence.append({
            "orden": match.get("orden", idx + 1), "hora": match.get("hora"),
            "jugador_a": a, "jugador_b": b,
            "marcador_sets": f"{score[0]}:{score[1]}", "ganador": winner,
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
        })

    ratings = {}
    for name in names:
        raw = (rating_torneo or {}).get(name) or {}
        try:
            final_rating = float(raw["rating_final"]) if raw.get("rating_final") not in (None, "") else None
        except (TypeError, ValueError):
            final_rating = None
        try:
            delta = float(raw["variacion"]) if raw.get("variacion") not in (None, "") else None
        except (TypeError, ValueError):
            delta = None
        ratings[name] = {
            "rating_final": final_rating, "variacion_torneo": delta,
            "rating_inicial_estimado": final_rating - delta if final_rating is not None and delta is not None else None,
            "fuente": "seccion Players de la ficha del torneo",
        }
    expected = len(names) * (len(names) - 1) // 2
    return {
        "metodo": "resultados oficiales ordenados por hora; tabla reconstruida tras cada partido",
        "partidos_reconstruidos": len(sequence), "partidos_esperados": expected,
        "secuencia": sequence,
        "tabla_final_reconstruida": sequence[-1]["tabla_despues"] if sequence else [],
        "rating_por_jugador": ratings,
        "advertencias": warnings + (["La tabla usa puntos y sets; los desempates oficiales por puntos de juego/H2H no se simulan por partido."] if sequence else []),
        "completa": len(sequence) == expected and not warnings,
    }


def parsear_detalle_oficial(texto, grupo):
    """Lee tarjetas de partido multilínea del texto visible de la ficha oficial."""
    import re

    lines = [line.strip() for line in str(texto or "").replace("\u00a0", " ").splitlines() if line.strip()]
    ratings = {}
    for player in grupo:
        name = str(player.get("jugador") or "").strip()
        rating = str(player.get("rating") or "").strip()
        if name and rating:
            ratings.setdefault(rating, []).append(name)

    rating_data = {}
    # El bloque Players muestra nombre, juegos, rating y variación en líneas separadas.
    try:
        p_start = next(i for i, line in enumerate(lines) if line.casefold() == "players")
        g_start = next(i for i in range(p_start + 1, len(lines)) if lines[i].casefold() == "group")
        section = lines[p_start + 1:g_start]
        for player in grupo:
            name = str(player.get("jugador") or "").strip()
            for i, line in enumerate(section):
                if line.casefold() == name.casefold() and i + 3 < len(section):
                    games = section[i + 1]
                    final_rating = section[i + 2]
                    delta_text = section[i + 3]
                    if re.fullmatch(r"\d+\s*\([^)]*\)", games) and re.fullmatch(r"\d+", final_rating) and re.fullmatch(r"[+-]\s*\d+", delta_text):
                        rating_data[name] = {
                            "rating_final": int(final_rating),
                            "variacion": int(re.sub(r"\s", "", delta_text)),
                        }
                    break
    except StopIteration:
        pass

    try:
        start = next(i for i, line in enumerate(lines) if line.casefold() == "tournament games") + 1
    except StopIteration:
        return {"partidos": [], "rating_por_jugador": rating_data,
                "advertencias": [{"motivo": "no se encontró la sección Tournament games"}],
                "fuente": "texto visible de la ficha oficial"}

    matches, warnings = [], []
    stage = "group"
    i = start
    while i < len(lines):
        marker = lines[i].casefold()
        if marker == "for 3rd place":
            stage = "third_place"
            i += 1
            continue
        if marker == "final":
            stage = "final"
            i += 1
            continue
        if marker not in {"finished", "live", "planned", "upcoming"}:
            i += 1
            continue
        status = marker
        if i + 1 >= len(lines) or not re.fullmatch(r"\d{1,2}:\d{2}", lines[i + 1]):
            warnings.append({"motivo": "tarjeta sin hora reconocible"})
            i += 1
            continue
        hour = lines[i + 1]
        j = i + 2
        if j + 3 >= len(lines):
            warnings.append({"hora": hour, "motivo": "tarjeta de partido incompleta"})
            break
        r1 = re.fullmatch(r"\((\d+)\)", lines[j])
        name1 = lines[j + 1]
        r2 = re.fullmatch(r"\((\d+)\)", lines[j + 2])
        name2 = lines[j + 3]
        if not r1 or not r2:
            warnings.append({"hora": hour, "motivo": "no se encontraron los ratings de ambos jugadores"})
            i = j + 1
            continue
        a_list, b_list = ratings.get(r1.group(1), []), ratings.get(r2.group(1), [])
        if len(a_list) != 1 or len(b_list) != 1 or a_list[0] == b_list[0]:
            warnings.append({"hora": hour, "motivo": "rating no identifica jugadores de forma única"})
            i = j + 4
            continue
        score = None
        if status == "finished":
            if j + 5 < len(lines) and re.fullmatch(r"\d+", lines[j + 4]) and re.fullmatch(r"\d+", lines[j + 5]):
                score = f"{lines[j + 4]}:{lines[j + 5]}"
            else:
                warnings.append({"hora": hour, "motivo": "partido marcado FINISHED sin marcador completo"})
        elif status == "live":
            # Un marcador parcial en vivo no se registra como resultado final.
            pass
        matches.append({
            "orden": len(matches) + 1, "hora": hour, "estado": status,
            "jugador_a": a_list[0], "jugador_b": b_list[0],
            "nombre_a_en_ficha": name1, "nombre_b_en_ficha": name2,
            "marcador_sets": score, "fase": stage,
        })
        i = j + (6 if score is not None else 4)
    return {
        "partidos": matches, "rating_por_jugador": rating_data,
        "advertencias": warnings,
        "fuente": "texto visible de la ficha oficial; emparejamiento por rating",
    }
