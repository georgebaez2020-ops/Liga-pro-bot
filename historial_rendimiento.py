"""Acumulación histórica de resultados en contextos competitivos relevantes.

Solo atribuye contexto previo cuando existe una captura anterior al marcador.
Si el primer snapshot ya contiene el resultado, no inventa la tabla previa.
"""
from __future__ import annotations

import unicodedata
from collections import defaultdict
from copy import deepcopy

from inteligencia_torneo import _score, calcular_clasificacion


def _key(name):
    return unicodedata.normalize("NFKC", " ".join(str(name).split())).casefold()


def _valid_score(group, i, j):
    a = group[i].get("resultados") or []
    b = group[j].get("resultados") or []
    sa = _score(a[j] if j < len(a) else "")
    sb = _score(b[i] if i < len(b) else "")
    return sa if sa is not None and sb == (sa[1], sa[0]) else None


def _acumular_historial_presion_snapshots(snapshots):
    """Reconstruye nuevos resultados entre snapshots y agrega métricas por jugador.

    Cada snapshot debe tener tournament_id, captured_at y payload con grupos.
    El análisis se realiza con la tabla inmediatamente anterior al marcador.
    """
    ordered = sorted(
        snapshots,
        key=lambda item: (str(item.get("captured_at") or ""), str(item.get("tournament_id") or "")),
    )
    previous = {}
    seen_matches = set()
    players = defaultdict(lambda: {
        "jugador": "",
        "partidos_relevantes": 0,
        "victorias": 0,
        "derrotas": 0,
        "torneos_con_muestra": set(),
    })
    summary = {
        "snapshots_procesados": 0,
        "partidos_nuevos_detectados": 0,
        "partidos_relevantes": 0,
        "partidos_sin_contexto_previo": 0,
        "grupos_no_comparables": 0,
        "marcadores_inconsistentes_omitidos": 0,
    }

    for snapshot in ordered:
        tid = str(snapshot.get("tournament_id") or "")
        payload = snapshot.get("payload") or {}
        tournament = payload.get("torneo") if isinstance(payload.get("torneo"), dict) else payload
        groups = tournament.get("grupos") or []
        summary["snapshots_procesados"] += 1

        for group_no, current in enumerate(groups):
            state_key = (tid, group_no)
            old = previous.get(state_key)
            if old is None:
                # Primera captura: puede contener resultados anteriores a nuestra
                # observación. Se guarda como línea base, sin atribuir presión.
                for i in range(len(current)):
                    for j in range(i + 1, len(current)):
                        if _valid_score(current, i, j):
                            summary["partidos_sin_contexto_previo"] += 1
                previous[state_key] = deepcopy(current)
                continue

            if len(old) != len(current) or [
                str(p.get("jugador") or "").strip() for p in old
            ] != [str(p.get("jugador") or "").strip() for p in current]:
                summary["grupos_no_comparables"] += 1
                previous[state_key] = deepcopy(current)
                continue

            try:
                before_table = calcular_clasificacion(old)
            except (ValueError, TypeError, IndexError):
                summary["grupos_no_comparables"] += 1
                previous[state_key] = deepcopy(current)
                continue

            if before_table.get("marcadores_inconsistentes"):
                summary["marcadores_inconsistentes_omitidos"] += len(
                    before_table["marcadores_inconsistentes"]
                )
                previous[state_key] = deepcopy(current)
                continue

            cutoff = 2 if len(current) == 4 else 4 if len(current) == 5 else None
            if cutoff is None:
                summary["grupos_no_comparables"] += 1
                previous[state_key] = deepcopy(current)
                continue

            ranges = before_table["escenarios"]["jugadores"]
            for i in range(len(current)):
                for j in range(i + 1, len(current)):
                    score = _valid_score(current, i, j)
                    if score is None or _valid_score(old, i, j) is not None:
                        continue

                    name_a = str(current[i].get("jugador") or "").strip()
                    name_b = str(current[j].get("jugador") or "").strip()
                    match_key = (tid, group_no, tuple(sorted((_key(name_a), _key(name_b)))))
                    if match_key in seen_matches:
                        continue
                    seen_matches.add(match_key)
                    summary["partidos_nuevos_detectados"] += 1

                    relevant = []
                    for name in (name_a, name_b):
                        span = ranges.get(name, {})
                        low = span.get("puesto_minimo_posible", len(current))
                        high = span.get("puesto_maximo_posible", 1)
                        if low <= cutoff < high:
                            relevant.append(name)

                    if not relevant:
                        continue

                    summary["partidos_relevantes"] += 1
                    winner = name_a if score[0] > score[1] else name_b
                    for name in relevant:
                        key = _key(name)
                        row = players[key]
                        row["jugador"] = name
                        row["partidos_relevantes"] += 1
                        row["victorias" if name == winner else "derrotas"] += 1
                        row["torneos_con_muestra"].add(tid)

            previous[state_key] = deepcopy(current)

    output = []
    for key, row in sorted(players.items(), key=lambda item: item[1]["jugador"].casefold()):
        sample = row["partidos_relevantes"]
        output.append({
            **row,
            "torneos_con_muestra": len(row["torneos_con_muestra"]),
            "tasa_victoria": round(row["victorias"] / sample, 4) if sample else None,
            "muestra_suficiente": sample >= 10,
            "interpretacion": (
                "Sin muestra suficiente; no inferir una tendencia."
                if sample < 10 else
                "Tendencia descriptiva, no psicológica; revisar rivales y formato."
            ),
        })

    return {
        "resumen": summary,
        "jugadores": output,
        "limitaciones": [
            "Solo se cuentan partidos cuyo marcador apareció entre dos snapshots comparables.",
            "La primera captura de cada grupo sirve como línea base; sus resultados previos no se atribuyen.",
            "Los partidos nuevos en una misma captura comparten el mismo contexto previo observado.",
            "El corte se estima con puntos y escenarios; los desempates pueden modificar posiciones.",
            "No mide presión psicológica ni puntos decisivos dentro de un set.",
        ],
    }



def acumular_historial_presion_reconstruido(snapshots):
    """Agrega respuestas a necesidad de ganar desde secuencias cronológicas completas.

    Usa la reconstrucción guardada en cada ficha. Solo cuenta grupos cuya
    secuencia de partidos esté completa; así no supone que los partidos que
    faltan en una ficha todavía estaban pendientes.
    """
    ordered = sorted(
        snapshots,
        key=lambda item: (str(item.get("captured_at") or ""), str(item.get("tournament_id") or "")),
    )
    # Una ficha puede aparecer en varios snapshots; usar una sola reconstrucción
    # completa por torneo/grupo evita contar el mismo partido varias veces.
    selected = {}
    summary = {
        "snapshots_procesados": len(ordered),
        "grupos_con_reconstruccion_completa": 0,
        "grupos_incompletos_omitidos": 0,
        "partidos_reconstruidos": 0,
        "jugadores_obligados_a_ganar": 0,
        "jugadores_sin_necesidad_estricta": 0,
    }
    incomplete_groups = set()
    for snapshot in ordered:
        tid = str(snapshot.get("tournament_id") or "")
        payload = snapshot.get("payload") or {}
        tournament = payload.get("torneo") if isinstance(payload.get("torneo"), dict) else payload
        for item in tournament.get("analisis_cronologico") or []:
            reconstruction = item.get("reconstruccion") or {}
            group_no = item.get("grupo")
            key = (tid, str(group_no))
            if reconstruction.get("completa"):
                selected[key] = (tid, group_no, reconstruction)
            else:
                incomplete_groups.add(key)
    summary["grupos_incompletos_omitidos"] = len(incomplete_groups - set(selected))

    players = defaultdict(lambda: {
        "jugador": "", "partidos_relevantes": 0, "victorias": 0,
        "derrotas": 0, "torneos_con_muestra": set(),
    })
    for (tid, _), (tournament_id, group_no, reconstruction) in selected.items():
        summary["grupos_con_reconstruccion_completa"] += 1
        sequence = reconstruction.get("secuencia") or []
        summary["partidos_reconstruidos"] += len(sequence)
        for match in sequence:
            needs = match.get("necesidad_antes") or {}
            outcomes = match.get("cumplio_necesidad") or {}
            for name, detail in needs.items():
                if not detail.get("debe_ganar_por_puntos_para_seguir_en_fase"):
                    summary["jugadores_sin_necesidad_estricta"] += 1
                    continue
                summary["jugadores_obligados_a_ganar"] += 1
                outcome = outcomes.get(name)
                # None indica que no se clasificó como obligación estricta.
                if outcome is None:
                    continue
                row = players[_key(name)]
                row["jugador"] = name
                row["partidos_relevantes"] += 1
                row["victorias" if outcome else "derrotas"] += 1
                row["torneos_con_muestra"].add(tournament_id)

    output = []
    for _, row in sorted(players.items(), key=lambda item: item[1]["jugador"].casefold()):
        sample = row["partidos_relevantes"]
        output.append({
            **row,
            "torneos_con_muestra": len(row["torneos_con_muestra"]),
            "tasa_victoria": round(row["victorias"] / sample, 4) if sample else None,
            "muestra_suficiente": sample >= 10,
            "interpretacion": (
                "Sin muestra suficiente; no inferir una tendencia."
                if sample < 10 else
                "Tendencia descriptiva de resultados en partidos que debía ganar; no mide presión psicológica."
            ),
        })
    return {
        "resumen": summary,
        "jugadores": output,
        "limitaciones": [
            "Solo se incluyen grupos con reconstrucción completa de todos los partidos esperados.",
            "La necesidad se estima por puntos de partido; los desempates pueden cambiar la clasificación.",
            "No mide presión psicológica ni puntos decisivos dentro de un set.",
        ],
    }


def acumular_historial_presion(snapshots):
    """Prefiere la reconstrucción cronológica completa; conserva fallback legacy."""
    reconstructed = acumular_historial_presion_reconstruido(snapshots)
    if reconstructed["resumen"]["jugadores_obligados_a_ganar"] > 0:
        return reconstructed
    return _acumular_historial_presion_snapshots(snapshots)


def analizar_historial_guardado(db):
    """Lee los snapshots persistidos y devuelve el acumulado histórico."""
    return acumular_historial_presion(db.listar_snapshots())


if __name__ == "__main__":
    import json
    from pathlib import Path
    from db import HistoryDB

    report = analizar_historial_guardado(HistoryDB())
    Path("salida").mkdir(exist_ok=True)
    output = Path("salida/rendimiento_historico.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["resumen"], ensure_ascii=False))
    print(f"Informe generado: {output}")
