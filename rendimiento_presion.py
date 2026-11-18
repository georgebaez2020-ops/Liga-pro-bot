"""Métricas exploratorias de partidos potencialmente decisivos.

No mide presión psicológica ni clutch point: la fuente actual solo aporta
marcadores agregados por partido, no secuencias de puntos ni contexto en vivo.
"""
from __future__ import annotations

from copy import deepcopy
from inteligencia_torneo import _score, calcular_clasificacion


def analizar_rendimiento_presion(grupo):
    """Resume resultados en duelos cuyo desenlace podía mover al jugador
    a través del corte competitivo (top 2 en grupos de 4; top 4 en grupos de 5).

    Para estimar la tabla previa, retira temporalmente el duelo analizado y
    usa los escenarios de puntos restantes. Se excluyen grupos incompletos,
    marcadores no recíprocos y partidos sin resultado válido.
    """
    size = len(grupo)
    if size not in (4, 5):
        raise ValueError("El grupo debe tener exactamente 4 o 5 jugadores")

    cutoff = 2 if size == 4 else 4
    results = {
        str(player.get("jugador") or "").strip(): {
            "jugador": str(player.get("jugador") or "").strip(),
            "partidos_relevantes": 0,
            "victorias": 0,
            "derrotas": 0,
            "tasa_victoria": None,
            "muestra_suficiente": False,
            "interpretacion": "Sin muestra de partidos potencialmente decisivos.",
        }
        for player in grupo
    }

    matches_checked = 0
    for i in range(size):
        for j in range(i + 1, size):
            raw_a = (grupo[i].get("resultados") or [])
            raw_b = (grupo[j].get("resultados") or [])
            score_a = _score(raw_a[j] if j < len(raw_a) else "")
            score_b = _score(raw_b[i] if i < len(raw_b) else "")
            if score_a is None or score_b != (score_a[1], score_a[0]):
                continue

            before = deepcopy(grupo)
            before[i]["resultados"][j] = ""
            before[j]["resultados"][i] = ""
            table = calcular_clasificacion(before)
            ranges = table["escenarios"]["jugadores"]
            a_name = str(grupo[i].get("jugador") or "").strip()
            b_name = str(grupo[j].get("jugador") or "").strip()

            relevant = []
            for name in (a_name, b_name):
                span = ranges.get(name, {})
                low = span.get("puesto_minimo_posible", size)
                high = span.get("puesto_maximo_posible", 1)
                if low <= cutoff < high:
                    relevant.append(name)

            if not relevant:
                continue

            matches_checked += 1
            winner = a_name if score_a[0] > score_a[1] else b_name
            loser = b_name if winner == a_name else a_name
            for name in relevant:
                row = results[name]
                row["partidos_relevantes"] += 1
                row["victorias" if name == winner else "derrotas"] += 1

    for row in results.values():
        sample = row["partidos_relevantes"]
        if sample:
            row["tasa_victoria"] = round(row["victorias"] / sample, 4)
            row["muestra_suficiente"] = sample >= 10
            row["interpretacion"] = (
                "Muestra exploratoria; no permite inferir comportamiento psicológico."
                if sample < 10 else
                "Tendencia descriptiva; requiere más torneos y control de rivales."
            )

    return {
        "metrica": "resultado_en_partidos_potencialmente_decisivos",
        "partidos_relevantes_detectados": matches_checked,
        "corte_reglamentario": f"top {cutoff}",
        "jugadores": results,
        "limitaciones": [
            "Es un proxy de importancia competitiva, no una medición psicológica de presión.",
            "No hay secuencia de puntos por set para medir clutch points o remontadas.",
            "La clasificación previa se estima por puntos; desempates futuros pueden cambiarla.",
            "No se etiqueta una tendencia con muestra inferior a 10 partidos.",
        ],
    }
