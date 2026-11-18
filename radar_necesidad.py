"""Radar histórico de necesidad de victoria (solo snapshots comparables)."""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from itertools import combinations, product
import unicodedata
from inteligencia_torneo import _score


def _key(v):
    return unicodedata.normalize("NFKC", " ".join(str(v or "").split())).casefold()


def _score_pair(group, i, j):
    a, b = group[i].get("resultados") or [], group[j].get("resultados") or []
    x = _score(a[j] if j < len(a) else "")
    y = _score(b[i] if i < len(b) else "")
    return x if x is not None and y == (x[1], x[0]) else None


def _pending(group):
    return [(i, j) for i, j in combinations(range(len(group)), 2)
            if _score_pair(group, i, j) is None]


def _best_place(group, player, forced_pair, forced_winner):
    n = len(group)
    points = [0] * n
    pending = _pending(group)
    for i, j in combinations(range(n), 2):
        score = _score_pair(group, i, j)
        if score:
            points[i] += 2 if score[0] > score[1] else 1
            points[j] += 2 if score[1] > score[0] else 1
    choices = [([forced_winner] if (i, j) == forced_pair else [i, j]) for i, j in pending]
    best = n
    for winners in product(*choices):
        totals = points[:]
        for (i, j), winner in zip(pending, winners):
            totals[winner] += 2
            totals[j if winner == i else i] += 1
        best = min(best, 1 + sum(x > totals[player] for x in totals))
    return best


def clasificar_necesidad(grupo, i, j):
    n = len(grupo)
    if n not in (4, 5) or _score_pair(grupo, i, j) is not None:
        return {}
    corte_fase = 2 if n == 4 else 4
    corte_final = 2
    out = {}
    for player, opponent in ((i, j), (j, i)):
        win_phase = _best_place(grupo, player, (i, j), player) <= corte_fase
        loss_phase = _best_place(grupo, player, (i, j), opponent) <= corte_fase
        win_final = _best_place(grupo, player, (i, j), player) <= corte_final
        loss_final = _best_place(grupo, player, (i, j), opponent) <= corte_final
        out[str(grupo[player].get("jugador") or "").strip()] = {
            "rival": str(grupo[opponent].get("jugador") or "").strip(),
            "necesidad_fase_final": ("debe_ganar" if win_phase and not loss_phase else
                                     "ganar_mejora_opciones" if win_phase else "sin_camino_por_puntos"),
            "necesidad_final": ("debe_ganar" if win_final and not loss_final else
                                "ganar_mejora_opciones" if win_final else "sin_camino_por_puntos"),
            "mejor_puesto_si_gana": _best_place(grupo, player, (i, j), player),
            "mejor_puesto_si_pierde": _best_place(grupo, player, (i, j), opponent),
            "criterio": "escenarios de puntos; desempates no simulados",
        }
    return out


def acumular_radar_necesidad(snapshots):
    ordered = sorted(snapshots, key=lambda x: (str(x.get("captured_at") or ""), str(x.get("tournament_id") or "")))
    previous, seen = {}, set()
    players = defaultdict(lambda: {
        "jugador": "", "partidos_con_necesidad": 0, "partidos_obligado_a_ganar": 0,
        "victorias_obligado": 0, "derrotas_obligado": 0, "torneos": set()
    })
    summary = {"snapshots_procesados": 0, "partidos_nuevos": 0,
               "partidos_con_contexto": 0, "partidos_sin_contexto": 0,
               "grupos_no_comparables": 0}
    for snap in ordered:
        tid = str(snap.get("tournament_id") or "")
        payload = snap.get("payload") or {}
        tournament = payload.get("torneo") if isinstance(payload.get("torneo"), dict) else payload
        groups = tournament.get("grupos") or []
        summary["snapshots_procesados"] += 1
        for group_no, current in enumerate(groups):
            state = (tid, group_no)
            old = previous.get(state)
            if old is None:
                summary["partidos_sin_contexto"] += sum(
                    _score_pair(current, i, j) is not None for i, j in combinations(range(len(current)), 2))
                previous[state] = deepcopy(current)
                continue
            if len(old) != len(current) or [_key(p.get("jugador")) for p in old] != [_key(p.get("jugador")) for p in current]:
                summary["grupos_no_comparables"] += 1
                previous[state] = deepcopy(current)
                continue
            for i, j in combinations(range(len(current)), 2):
                score = _score_pair(current, i, j)
                if score is None or _score_pair(old, i, j) is not None:
                    continue
                names = [str(current[i].get("jugador") or "").strip(),
                         str(current[j].get("jugador") or "").strip()]
                key = (tid, group_no, tuple(sorted(map(_key, names))))
                if key in seen:
                    continue
                seen.add(key)
                summary["partidos_nuevos"] += 1
                context = clasificar_necesidad(old, i, j)
                if not context:
                    continue
                summary["partidos_con_contexto"] += 1
                winner = i if score[0] > score[1] else j
                for name, detail in context.items():
                    row = players[_key(name)]
                    row["jugador"] = name
                    row["torneos"].add(tid)
                    need = detail["necesidad_fase_final"]
                    if need in ("debe_ganar", "ganar_mejora_opciones"):
                        row["partidos_con_necesidad"] += 1
                    if need == "debe_ganar":
                        row["partidos_obligado_a_ganar"] += 1
                        if (name == names[0] and winner == i) or (name == names[1] and winner == j):
                            row["victorias_obligado"] += 1
                        else:
                            row["derrotas_obligado"] += 1
            previous[state] = deepcopy(current)
    output = []
    for row in players.values():
        n = row["partidos_obligado_a_ganar"]
        row["torneos"] = len(row["torneos"])
        row["respuesta_cuando_obligado"] = round(row["victorias_obligado"] / n, 4) if n else None
        row["muestra_suficiente"] = n >= 10
        row["interpretacion"] = ("Muestra insuficiente; no clasificar al jugador." if n < 10 else
                                 "Tendencia descriptiva; contrastar rivales, rating y formato.")
        output.append(row)
    output.sort(key=lambda x: x["jugador"].casefold())
    return {"resumen": summary, "jugadores": output, "limitaciones": [
        "Solo se analizan resultados que aparecen entre snapshots comparables.",
        "La necesidad se estima por puntos; los desempates no se simulan.",
        "No mide presión psicológica ni puntos decisivos dentro de los sets.",
        "Menos de 10 partidos obligatorios no permite clasificar una tendencia."
    ]}


if __name__ == "__main__":
    import json
    from pathlib import Path
    from db import HistoryDB
    report = acumular_radar_necesidad(HistoryDB().listar_snapshots())
    Path("salida").mkdir(exist_ok=True)
    Path("salida/radar_necesidad.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["resumen"], ensure_ascii=False))
    print("Informe generado: salida/radar_necesidad.json")
