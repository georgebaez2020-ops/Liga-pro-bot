"""Construye estadísticas históricas conservadoras a partir de tablas terminadas.

No interpreta celdas vacías, marcadores parciales ni tablas en vivo como resultados.
Solo cuenta marcadores completos y verifica que el rival tenga el marcador inverso.
"""
import csv
import json
import os
import re
from collections import defaultdict

SCORE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")


def score(cell):
    match = SCORE.match(str(cell or ""))
    if not match:
        return None
    a, b = map(int, match.groups())
    if a == b:
        return None
    return a, b


def analyze(data):
    players = defaultdict(lambda: {
        "jugador": "", "rating_values": [], "torneos": [],
        "partidos": 0, "victorias": 0, "derrotas": 0,
        "marcadores_incompletos": 0
    })
    h2h = defaultdict(lambda: {"jugador_a": "", "jugador_b": "", "partidos": 0,
                               "victorias_a": 0, "victorias_b": 0})
    checked = consistent = inconsistent = 0
    issues = []

    for tournament_id, tournament in data.get("torneos", {}).items():
        if tournament.get("estado") != "finished":
            continue
        for group_number, group in enumerate(tournament.get("grupos", []), 1):
            names = [str(p.get("jugador", "")).strip() for p in group]
            for p in group:
                name = str(p.get("jugador", "")).strip()
                if not name:
                    issues.append({"torneo": tournament_id, "problema": "jugador sin nombre"})
                    continue
                s = players[name]
                s["jugador"] = name
                rating = str(p.get("rating", "")).strip()
                if rating.isdigit():
                    s["rating_values"].append(int(rating))
                if tournament_id not in s["torneos"]:
                    s["torneos"].append(tournament_id)

            for i, p in enumerate(group):
                name_a = str(p.get("jugador", "")).strip()
                results_a = p.get("resultados", [])
                for j in range(i + 1, len(group)):
                    q = group[j]
                    name_b = str(q.get("jugador", "")).strip()
                    results_b = q.get("resultados", [])
                    raw_a = results_a[j] if j < len(results_a) else ""
                    raw_b = results_b[i] if i < len(results_b) else ""
                    sa, sb = score(raw_a), score(raw_b)

                    # No usar marcadores que no coincidan en las dos filas.
                    if sa is None or sb is None:
                        if str(raw_a).strip() not in ("", ":", "|||") or str(raw_b).strip() not in ("", ":", "|||"):
                            issues.append({"torneo": tournament_id, "jugador_a": name_a,
                                           "jugador_b": name_b, "problema": "marcador ausente o no interpretable",
                                           "celda_a": str(raw_a), "celda_b": str(raw_b)})
                        continue
                    checked += 1
                    if sa[0] != sb[1] or sa[1] != sb[0]:
                        inconsistent += 1
                        issues.append({"torneo": tournament_id, "jugador_a": name_a,
                                       "jugador_b": name_b, "problema": "marcadores no recíprocos",
                                       "celda_a": str(raw_a), "celda_b": str(raw_b)})
                        continue
                    consistent += 1
                    for nm, sc in ((name_a, sa), (name_b, sb)):
                        ps = players[nm]
                        ps["partidos"] += 1
                        if sc[0] > sc[1]:
                            ps["victorias"] += 1
                        else:
                            ps["derrotas"] += 1
                    key = tuple(sorted((name_a, name_b), key=str.casefold))
                    h = h2h[key]
                    h["jugador_a"], h["jugador_b"] = key
                    h["partidos"] += 1
                    if sa[0] > sa[1]:
                        h["victorias_a"] += 1
                    else:
                        h["victorias_b"] += 1

    player_rows = []
    for p in players.values():
        vals = p.pop("rating_values")
        p["rating_promedio_observado"] = round(sum(vals) / len(vals), 1) if vals else None
        p["porcentaje_victorias"] = round(100 * p["victorias"] / p["partidos"], 1) if p["partidos"] else None
        p["torneos"] = sorted(p["torneos"])
        player_rows.append(p)
    player_rows.sort(key=lambda x: (-(x["porcentaje_victorias"] or -1), -x["partidos"], x["jugador"].casefold()))

    h2h_rows = sorted(h2h.values(), key=lambda x: (x["jugador_a"].casefold(), x["jugador_b"].casefold()))
    return {
        "fuente": "tablas de torneos con estado finished",
        "advertencia": "Estadísticas descriptivas; no son probabilidades de victoria. No se usan torneos live ni upcoming.",
        "validacion": {"duelos_con_marcador_completo": checked, "duelos_reciprocos_validos": consistent,
                       "duelos_inconsistentes": inconsistent, "incidencias": len(issues)},
        "jugadores": player_rows, "enfrentamientos_directos": h2h_rows, "incidencias": issues
    }


def main():
    os.makedirs("salida", exist_ok=True)
    with open("salida/tablas.json", encoding="utf-8") as f:
        source = json.load(f)
    result = analyze(source)
    with open("salida/jugadores.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open("salida/jugadores.csv", "w", newline="", encoding="utf-8") as f:
        fields = ["jugador", "partidos", "victorias", "derrotas", "porcentaje_victorias",
                  "rating_promedio_observado", "torneos"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for p in result["jugadores"]:
            writer.writerow({**p, "torneos": "|".join(p["torneos"])})
    print("Validación estadística:", json.dumps(result["validacion"], ensure_ascii=False))
    print("Jugadores con historial:", len(result["jugadores"]))
    print("Enfrentamientos directos:", len(result["enfrentamientos_directos"]))


if __name__ == "__main__":
    main()
