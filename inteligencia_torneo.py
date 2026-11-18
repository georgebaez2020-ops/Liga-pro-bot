"""Inteligencia de fase de grupos para Czech Liga Pro.

Calcula una clasificación provisional desde marcadores recíprocos completos.
No infiere retiros, lesiones, descalificaciones ni walkovers: esos casos
requieren una etiqueta explícita de la fuente antes de aplicar el reglamento.
"""
from __future__ import annotations

import re
from collections import defaultdict
from itertools import combinations

SCORE_RE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")
PAIR_RE = re.compile(r"^\s*(\d+)\s*[-:]\s*(\d+)\s*$")


def _score(value):
    match = SCORE_RE.fullmatch(str(value or ""))
    if not match:
        return None
    a, b = map(int, match.groups())
    return (a, b) if a != b else None


def _pair(value):
    match = PAIR_RE.fullmatch(str(value or ""))
    return tuple(map(int, match.groups())) if match else (None, None)


def _player_name(player):
    return str(player.get("jugador") or "").strip()


def _group_size(group):
    return len(group) if len(group) in (4, 5) else None


def calcular_partidos_pendientes(grupo):
    """Devuelve duelos sin marcador recíproco completo; no asume su calendario."""
    pending, invalid = [], []
    for i, j in combinations(range(len(grupo)), 2):
        a, b = _player_name(grupo[i]), _player_name(grupo[j])
        ra = grupo[i].get("resultados") or []
        rb = grupo[j].get("resultados") or []
        raw_a = ra[j] if j < len(ra) else ""
        raw_b = rb[i] if i < len(rb) else ""
        sa, sb = _score(raw_a), _score(raw_b)
        duel = {"jugador_a": a, "jugador_b": b, "celda_a": raw_a, "celda_b": raw_b}
        if sa is None and sb is None:
            pending.append(duel)
        elif sa is None or sb is None or sa != (sb[1], sb[0]):
            invalid.append(duel)
    return {"pendientes": pending, "inconsistentes": invalid}


def _head_to_head(group, name_a, name_b):
    by_name = {_player_name(p): p for p in group}
    a, b = by_name.get(name_a), by_name.get(name_b)
    if not a or not b:
        return None
    i, j = list(map(_player_name, group)).index(name_a), list(map(_player_name, group)).index(name_b)
    ra, rb = a.get("resultados") or [], b.get("resultados") or []
    sa = _score(ra[j] if j < len(ra) else "")
    sb = _score(rb[i] if i < len(rb) else "")
    if sa is None or sb is None or sa != (sb[1], sb[0]):
        return None
    return 1 if sa[0] > sa[1] else -1


def calcular_clasificacion(grupo):
    """Aplica puntos 2/1 y desempates reglamentarios sobre resultados completos."""
    size = _group_size(grupo)
    if not size:
        raise ValueError("El grupo debe tener exactamente 4 o 5 jugadores")
    stats = {}
    for p in grupo:
        name = _player_name(p)
        if not name or name in stats:
            raise ValueError("Cada jugador debe tener un nombre único dentro del grupo")
        sets_for, sets_against = _pair(p.get("sets"))
        balls_for, balls_against = _pair(p.get("balls"))
        stats[name] = {
            "jugador": name, "rating": p.get("rating"), "partidos": 0,
            "victorias": 0, "derrotas": 0, "puntos_reglamento": 0,
            "sets_ganados_tabla": sets_for, "sets_perdidos_tabla": sets_against,
            "diferencia_sets_tabla": (sets_for - sets_against) if sets_for is not None else None,
            "puntos_juego_favor_tabla": balls_for,
            "puntos_juego_contra_tabla": balls_against,
            "diferencia_puntos_juego_tabla": (balls_for - balls_against) if balls_for is not None else None,
        }

    for i, j in combinations(range(size), 2):
        a, b = _player_name(grupo[i]), _player_name(grupo[j])
        ra, rb = grupo[i].get("resultados") or [], grupo[j].get("resultados") or []
        sa = _score(ra[j] if j < len(ra) else "")
        sb = _score(rb[i] if i < len(rb) else "")
        if sa is None or sb is None or sa != (sb[1], sb[0]):
            continue
        for name, score in ((a, sa), (b, sb)):
            row = stats[name]
            row["partidos"] += 1
            if score[0] > score[1]:
                row["victorias"] += 1
                row["puntos_reglamento"] += 2
            else:
                row["derrotas"] += 1
                row["puntos_reglamento"] += 1

    pending = calcular_partidos_pendientes(grupo)
    rows = list(stats.values())
    # Ordena únicamente con criterios oficiales cuantificables. Los empates
    # que lleguen al sorteo quedan señalados, no se resuelven arbitrariamente.
    def base_key(row):
        return (
            row["puntos_reglamento"],
            row["sets_ganados_tabla"] if row["sets_ganados_tabla"] is not None else -1,
            row["diferencia_sets_tabla"] if row["diferencia_sets_tabla"] is not None else -10**9,
            row["diferencia_puntos_juego_tabla"] if row["diferencia_puntos_juego_tabla"] is not None else -10**9,
            row["puntos_juego_favor_tabla"] if row["puntos_juego_favor_tabla"] is not None else -1,
        )

    rows.sort(key=lambda r: (tuple(-x for x in base_key(r)), r["jugador"].casefold()))
    # Reaplica H2H solo cuando exactamente dos jugadores siguen empatados
    # en todos los criterios previos; nunca resuelve empates de 3+ por H2H.
    start = 0
    while start < len(rows):
        end = start + 1
        while end < len(rows) and base_key(rows[start]) == base_key(rows[end]):
            end += 1
        tied = rows[start:end]
        if len(tied) == 2:
            result = _head_to_head(grupo, tied[0]["jugador"], tied[1]["jugador"])
            if result == -1:
                rows[start], rows[start + 1] = rows[start + 1], rows[start]
        start = end

    for index, row in enumerate(rows, 1):
        row["puesto_grupo"] = index
    unresolved = []
    for a, b in zip(rows, rows[1:]):
        if base_key(a) == base_key(b) and _head_to_head(grupo, a["jugador"], b["jugador"]) is None:
            unresolved.append([a["jugador"], b["jugador"]])

    resultado = {
        "formato": size,
        "clasificacion": rows,
        "partidos_pendientes": pending["pendientes"],
        "marcadores_inconsistentes": pending["inconsistentes"],
        "empates_no_resueltos": unresolved,
        "estado_clasificacion": "provisional" if pending["pendientes"] or pending["inconsistentes"] else "completa",
        "nota": "Los retiros, lesiones, descalificaciones y walkovers no se deducen de celdas vacías.",
    }
    resultado["escenarios"] = analizar_escenarios(resultado)
    return resultado


def analizar_escenarios(clasificacion):
    """Enumera resultados W/L de duelos pendientes y estima rangos de puesto.

    Los escenarios usan puntos reglamentarios (2/1). Si hay empate en puntos,
    devuelven un rango de puestos porque los desempates futuros dependen de
    sets/puntos que todavía no existen. No inventa marcadores de sets.
    """
    rows = clasificacion["clasificacion"]
    pending = clasificacion.get("partidos_pendientes", [])
    inconsistent = clasificacion.get("marcadores_inconsistentes", [])
    names = [row["jugador"] for row in rows]
    base = {row["jugador"]: row["puntos_reglamento"] for row in rows}
    min_place = {name: len(rows) for name in names}
    max_place = {name: 1 for name in names}
    total = 1 << len(pending)

    if not pending and not inconsistent:
        for row in rows:
            min_place[row["jugador"]] = row["puesto_grupo"]
            max_place[row["jugador"]] = row["puesto_grupo"]

    for mask in range(total):
        points = dict(base)
        for index, duel in enumerate(pending):
            winner = duel["jugador_a"] if (mask >> index) & 1 else duel["jugador_b"]
            loser = duel["jugador_b"] if winner == duel["jugador_a"] else duel["jugador_a"]
            points[winner] += 2
            points[loser] += 1

        ordered = sorted(names, key=lambda name: points[name], reverse=True)
        start = 0
        while start < len(ordered):
            end = start + 1
            while end < len(ordered) and points[ordered[end]] == points[ordered[start]]:
                end += 1
            for name in ordered[start:end]:
                min_place[name] = min(min_place[name], start + 1)
                max_place[name] = max(max_place[name], end)
            start = end

    escenarios = {}
    cutoff_fase = 4 if len(rows) == 5 else 2
    for name in names:
        low, high = min_place[name], max_place[name]
        escenarios[name] = {
            "puesto_minimo_posible": low,
            "puesto_maximo_posible": high,
            "puede_top_2": low <= 2,
            "asegura_top_2_por_puntos": high <= 2,
            "puede_fase_final": low <= cutoff_fase,
            "asegura_fase_final_por_puntos": high <= cutoff_fase,
        }

    return {
        "escenarios_evaluados": total,
        "duelos_pendientes_modelados": len(pending),
        "marcadores_inconsistentes_excluidos": len(inconsistent),
        "escenarios_completos": not inconsistent,
        "metodo": "enumeración de victorias/derrotas; empates por puntos expresados como rango",
        "advertencia": (
            "Los rangos son por puntos. Sets ganados, diferencia de sets, "
            "diferencia de puntos, puntos anotados y H2H pueden modificar "
            "el orden final; no se simulan marcadores futuros."
        ),
        "jugadores": escenarios,
    }



def evaluar_necesidad_jugador(clasificacion, jugador):
    """Describe el objetivo reglamentario actual; no afirma una clasificación matemática."""
    rows = clasificacion["clasificacion"]
    size = clasificacion["formato"]
    index = next((i for i, row in enumerate(rows) if row["jugador"] == jugador), None)
    if index is None:
        raise ValueError(f"Jugador no encontrado: {jugador}")
    place = index + 1
    pending = clasificacion["estado_clasificacion"] != "completa"
    if size == 4:
        objective = "disputar la final por el título" if place <= 2 else "disputar el partido por el tercer puesto"
        target = "top 2" if place <= 2 else "top 2 para llegar a la final"
    else:
        if place == 5:
            objective = "evitar la eliminación de la fase final"
            target = "top 4"
        elif place <= 2:
            objective = "disputar la final por el título"
            target = "top 2"
        else:
            objective = "asegurar un puesto entre los cuatro que disputan la fase final"
            target = "top 4"
    escenario = (clasificacion.get("escenarios") or {}).get("jugadores", {}).get(jugador)
    return {
        "jugador": jugador, "puesto_provisional": place, "objetivo_reglamentario": objective,
        "referencia": target, "requiere_atencion": pending, "escenario_por_puntos": escenario,
        "advertencia": "Puesto provisional: hay partidos pendientes o marcadores inconsistentes."
        if pending else "Clasificación de grupo completa; falta considerar el resultado de la fase final.",
    }


def analizar_torneo(torneo):
    """Analiza los grupos disponibles; no inventa la fase final si el scraper no la extrae."""
    resultado = []
    for numero, grupo in enumerate(torneo.get("grupos", []), 1):
        tabla = calcular_clasificacion(grupo)
        tabla["grupo"] = numero
        tabla["necesidades"] = [
            evaluar_necesidad_jugador(tabla, row["jugador"])
            for row in tabla["clasificacion"]
        ]
        resultado.append(tabla)
    return {
        "torneo_id": str(torneo.get("id") or ""),
        "estado_torneo": torneo.get("estado", "unknown"),
        "grupos": resultado,
        "fase_final_disponible": bool(torneo.get("fase_final")),
        "advertencia_fase_final": (
            "La fuente extraída aún no aporta resultados de la fase final; "
            "el puesto definitivo del torneo no se puede calcular."
        ),
    }



def integrar_inteligencia_en_resultado(resultado):
    """Añade el análisis de grupos a cada torneo extraído, sin alterar los datos fuente."""
    resumen = {
        "torneos_analizados": 0,
        "grupos_analizados": 0,
        "jugadores_analizados": 0,
        "partidos_pendientes": 0,
        "marcadores_inconsistentes": 0,
        "errores": 0,
    }
    for torneo in resultado.get("torneos", {}).values():
        try:
            analisis = analizar_torneo(torneo)
            torneo["inteligencia"] = analisis
            resumen["torneos_analizados"] += 1
            for grupo in analisis["grupos"]:
                resumen["grupos_analizados"] += 1
                resumen["jugadores_analizados"] += len(grupo["clasificacion"])
                resumen["partidos_pendientes"] += len(grupo["partidos_pendientes"])
                resumen["marcadores_inconsistentes"] += len(grupo["marcadores_inconsistentes"])
        except Exception as exc:
            torneo["inteligencia_error"] = f"{type(exc).__name__}: {str(exc)[:250]}"
            resumen["errores"] += 1
    resultado["resumen_inteligencia"] = resumen
    return resultado
