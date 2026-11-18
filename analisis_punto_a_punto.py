"""Métricas descriptivas para secuencias punto a punto."""
from collections import Counter


def analizar_puntos(puntos):
    """Entrada: lista cronológica de {set: int, ganador: 'A'|'B'}."""
    sets, warnings = [], []
    actual = None
    streak = Counter()
    max_streak = Counter()
    desde_8 = Counter()
    remontadas = Counter()
    cierres = Counter()
    cambios = 0
    lider_previo = None

    for i, p in enumerate(puntos or [], 1):
        if not isinstance(p, dict) or str(p.get("ganador", "")).upper() not in ("A", "B"):
            warnings.append({"indice": i, "motivo": "punto inválido; ganador debe ser A o B"})
            continue
        try:
            nset = int(p.get("set", 1))
        except (TypeError, ValueError):
            warnings.append({"indice": i, "motivo": "número de set inválido"})
            continue
        if nset < 1:
            warnings.append({"indice": i, "motivo": "número de set inválido"})
            continue
        if actual is None or nset != actual["set"]:
            if actual is not None:
                if nset != actual["set"] + 1:
                    warnings.append({"indice": i, "motivo": "salto o retroceso de set"})
                    continue
                sets.append(actual)
            actual = {"set": nset, "a": 0, "b": 0, "secuencia": []}
            streak = Counter()
            lider_previo = None

        a, b = actual["a"], actual["b"]
        if max(a, b) >= 11 and abs(a-b) >= 2:
            warnings.append({"indice": i, "motivo": "punto recibido después del cierre del set"})
            continue
        winner = str(p["ganador"]).upper()
        if a >= 8 and b >= 8:
            desde_8[winner] += 1
        if winner == "A":
            if b-a >= 3:
                remontadas["A"] += 1
            a += 1
        else:
            if a-b >= 3:
                remontadas["B"] += 1
            b += 1
        actual["a"], actual["b"] = a, b
        actual["secuencia"].append(winner)
        streak[winner] += 1
        streak["B" if winner == "A" else "A"] = 0
        max_streak[winner] = max(max_streak[winner], streak[winner])
        leader = "A" if a > b else "B" if b > a else None
        if leader and lider_previo and leader != lider_previo:
            cambios += 1
        if leader:
            lider_previo = leader
        if max(a, b) >= 11 and abs(a-b) >= 2:
            cierres[winner] += 1

    if actual is not None:
        sets.append(actual)
    summary = [{
        "set": s["set"], "marcador": f'{s["a"]}:{s["b"]}',
        "puntos_totales": s["a"]+s["b"],
        "ganador": "A" if s["a"] > s["b"] else "B" if s["b"] > s["a"] else None,
        "finalizado": max(s["a"], s["b"]) >= 11 and abs(s["a"]-s["b"]) >= 2,
    } for s in sets]
    return {
        "sets_observados": len(summary), "sets": summary,
        "puntos_totales_a": sum(s["a"] for s in sets),
        "puntos_totales_b": sum(s["b"] for s in sets),
        "racha_maxima": {x: max_streak[x] for x in ("A", "B")},
        "puntos_ganados_desde_8_8": dict(desde_8),
        "puntos_ganados_remontando_deficit_3": dict(remontadas),
        "puntos_de_cierre": dict(cierres), "cambios_de_liderato": cambios,
        "todos_los_sets_finalizados": bool(summary) and all(s["finalizado"] for s in summary),
        "advertencias": warnings,
        "limitaciones": [
            "No estima el saque ni otras variables que la fuente no entregue.",
            "Describe secuencias; no demuestra fortaleza mental ni predice por sí solo resultados.",
            "Un set incompleto no se presenta como finalizado."
        ],
    }
