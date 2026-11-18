"""Integra secuencias punto a punto en perfiles acumulados de jugadores."""
from __future__ import annotations

from collections import Counter, defaultdict

from analisis_punto_a_punto import analizar_puntos


def construir_perfiles_punto_a_punto(partidos):
    """Cada partido: jugador_a, jugador_b, puntos=[{set, ganador:'A'|'B'}].

    Los puntos se atribuyen por la perspectiva A/B del partido. Solo se aceptan
    secuencias sin advertencias; los datos incompletos pueden aportar puntos
    observados, pero nunca se etiquetan como partido completo.
    """
    stats = defaultdict(lambda: {
        "partidos_con_secuencia": 0, "partidos_con_todos_los_sets_finalizados": 0,
        "puntos_jugados": 0, "puntos_ganados": 0,
        "puntos_ganados_desde_8_8": 0, "puntos_ganados_remontando_deficit_3": 0,
        "puntos_de_cierre": 0, "racha_maxima": 0, "sets_observados": 0,
        "sets_finalizados": 0,
    })
    names = {}
    detalles = []
    warnings = []

    for idx, match in enumerate(partidos or [], 1):
        a = str(match.get("jugador_a") or "").strip()
        b = str(match.get("jugador_b") or "").strip()
        if not a or not b or a.casefold() == b.casefold():
            warnings.append({"partido": idx, "motivo": "jugadores no identificados"})
            continue
        points = match.get("puntos") or []
        report = analizar_puntos(points)
        if report["advertencias"]:
            warnings.append({"partido": idx, "motivo": "secuencia con puntos inválidos", "detalle": report["advertencias"]})
            continue
        if not points:
            warnings.append({"partido": idx, "motivo": "sin secuencia de puntos"})
            continue

        names[a.casefold()], names[b.casefold()] = a, b
        sa, sb = stats[a.casefold()], stats[b.casefold()]
        sa["partidos_con_secuencia"] += 1
        sb["partidos_con_secuencia"] += 1
        sa["partidos_con_todos_los_sets_finalizados"] += int(report["todos_los_sets_finalizados"])
        sb["partidos_con_todos_los_sets_finalizados"] += int(report["todos_los_sets_finalizados"])
        sa["puntos_jugados"] += report["puntos_totales_a"] + report["puntos_totales_b"]
        sb["puntos_jugados"] += report["puntos_totales_a"] + report["puntos_totales_b"]
        sa["puntos_ganados"] += report["puntos_totales_a"]
        sb["puntos_ganados"] += report["puntos_totales_b"]
        sa["puntos_ganados_desde_8_8"] += report["puntos_ganados_desde_8_8"].get("A", 0)
        sb["puntos_ganados_desde_8_8"] += report["puntos_ganados_desde_8_8"].get("B", 0)
        sa["puntos_ganados_remontando_deficit_3"] += report["puntos_ganados_remontando_deficit_3"].get("A", 0)
        sb["puntos_ganados_remontando_deficit_3"] += report["puntos_ganados_remontando_deficit_3"].get("B", 0)
        sa["puntos_de_cierre"] += report["puntos_de_cierre"].get("A", 0)
        sb["puntos_de_cierre"] += report["puntos_de_cierre"].get("B", 0)
        sa["racha_maxima"] = max(sa["racha_maxima"], report["racha_maxima"]["A"])
        sb["racha_maxima"] = max(sb["racha_maxima"], report["racha_maxima"]["B"])
        sa["sets_observados"] += report["sets_observados"]
        sb["sets_observados"] += report["sets_observados"]
        finished = sum(1 for s in report["sets"] if s["finalizado"])
        sa["sets_finalizados"] += finished
        sb["sets_finalizados"] += finished
        detalles.append({
            "partido": idx, "jugador_a": a, "jugador_b": b,
            "analisis": report,
        })

    profiles = []
    for key, row in sorted(stats.items(), key=lambda item: names[item[0]].casefold()):
        profiles.append({
            "jugador": names[key],
            **row,
            "porcentaje_puntos_ganados": round(100 * row["puntos_ganados"] / row["puntos_jugados"], 2) if row["puntos_jugados"] else None,
            "porcentaje_puntos_ganados_desde_8_8": None,
            "muestra_suficiente": row["partidos_con_secuencia"] >= 30,
        })
    return {
        "resumen": {
            "partidos_con_secuencia": len(detalles),
            "jugadores_analizados": len(profiles),
            "partidos_descartados_o_incompletos": len(warnings),
        },
        "jugadores": profiles,
        "partidos": detalles,
        "advertencias": warnings,
        "criterios": [
            "La secuencia debe estar ordenada cronológicamente y cada punto debe identificar al ganador A/B.",
            "Porcentaje de puntos ganados = puntos ganados / puntos disputados observados.",
            "No se calcula porcentaje de puntos decisivos sin disponer del denominador completo de oportunidades.",
            "Muestra suficiente se marca desde 30 partidos con secuencia; no implica capacidad predictiva.",
        ],
    }
