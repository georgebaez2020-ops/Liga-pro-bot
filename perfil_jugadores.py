"""Perfiles estadísticos acumulados a partir de snapshots históricos.

Solo considera marcadores completos de partido al mejor de cinco (3:0, 3:1 o 3:2),
recíprocos en ambas filas. No interpreta marcadores parciales en vivo como finales.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict


def _key(name):
    return unicodedata.normalize("NFKC", " ".join(str(name or "").split())).casefold()


def _score(value):
    match = re.fullmatch(r"\s*(\d+)\s*:\s*(\d+)\s*", str(value or ""))
    if not match:
        return None
    a, b = map(int, match.groups())
    if a == 3 and 0 <= b <= 2:
        return a, b
    if b == 3 and 0 <= a <= 2:
        return a, b
    return None


def extraer_partidos_historicos(snapshots):
    """Extrae una sola fila por partido finalizado, sin contar snapshots repetidos."""
    partidos = {}
    ordenados = sorted(
        snapshots,
        key=lambda s: (str(s.get("captured_at") or ""), str(s.get("tournament_id") or "")),
    )
    for snap in ordenados:
        tid = str(snap.get("tournament_id") or "")
        payload = snap.get("payload") or {}
        torneo = payload.get("torneo") if isinstance(payload.get("torneo"), dict) else payload
        for group_no, group in enumerate(torneo.get("grupos") or [], start=1):
            for i, a in enumerate(group):
                for j in range(i + 1, len(group)):
                    b = group[j]
                    names = (str(a.get("jugador") or "").strip(), str(b.get("jugador") or "").strip())
                    ka, kb = _key(names[0]), _key(names[1])
                    if not ka or not kb or ka == kb:
                        continue
                    ra, rb = a.get("resultados") or [], b.get("resultados") or []
                    sa = _score(ra[j] if j < len(ra) else "")
                    sb = _score(rb[i] if i < len(rb) else "")
                    if sa is None or sb != (sa[1], sa[0]):
                        continue
                    # Canonical player order keeps the result orientation stable.
                    if ka < kb:
                        p1, p2, score = names[0], names[1], sa
                        rating1, rating2 = a.get("rating"), b.get("rating")
                    else:
                        p1, p2, score = names[1], names[0], (sa[1], sa[0])
                        rating1, rating2 = b.get("rating"), a.get("rating")
                    key = (tid, group_no, ka if ka < kb else kb, kb if ka < kb else ka)
                    candidate = {
                        "torneo_id": tid,
                        "grupo": group_no,
                        "fecha_captura": str(snap.get("captured_at") or ""),
                        "jugador_a": p1,
                        "jugador_b": p2,
                        "sets_a": score[0],
                        "sets_b": score[1],
                        "rating_a": rating1,
                        "rating_b": rating2,
                    }
                    # First complete observation is retained to avoid snapshot duplication.
                    partidos.setdefault(key, candidate)
    return sorted(partidos.values(), key=lambda m: (m["fecha_captura"], m["torneo_id"], m["grupo"]))


def _metrics(matches, player_key):
    wins = losses = sets_for = sets_against = straight_wins = deciders_won = deciders_lost = 0
    for m in matches:
        is_a = _key(m["jugador_a"]) == player_key
        own = m["sets_a"] if is_a else m["sets_b"]
        opp = m["sets_b"] if is_a else m["sets_a"]
        sets_for += own
        sets_against += opp
        if own > opp:
            wins += 1
            straight_wins += int(own == 3 and opp == 0)
            deciders_won += int(own == 3 and opp == 2)
        else:
            losses += 1
            deciders_lost += int(own == 2 and opp == 3)
    total = wins + losses
    return {
        "partidos": total,
        "victorias": wins,
        "derrotas": losses,
        "porcentaje_victorias": round(100 * wins / total, 1) if total else None,
        "sets_a_favor": sets_for,
        "sets_en_contra": sets_against,
        "diferencia_sets": sets_for - sets_against,
        "victorias_3_0": straight_wins,
        "decisivos_3_2_ganados": deciders_won,
        "decisivos_2_3_perdidos": deciders_lost,
    }


def construir_perfiles(snapshots):
    """Genera métricas globales y ventanas móviles de 10, 30 y 60 partidos."""
    matches = extraer_partidos_historicos(snapshots)
    by_player = defaultdict(list)
    names = {}
    head_to_head = defaultdict(list)
    for m in matches:
        ka, kb = _key(m["jugador_a"]), _key(m["jugador_b"])
        by_player[ka].append(m)
        by_player[kb].append(m)
        names[ka], names[kb] = m["jugador_a"], m["jugador_b"]
        pair = tuple(sorted((ka, kb)))
        head_to_head[pair].append(m)

    profiles = []
    for key, rows in sorted(by_player.items(), key=lambda x: names[x[0]].casefold()):
        ordered = sorted(rows, key=lambda m: (m["fecha_captura"], m["torneo_id"]))
        profile = {
            "jugador": names[key],
            "total_partidos_historicos": len(ordered),
            "global": _metrics(ordered, key),
            "ventanas": {
                str(n): _metrics(ordered[-n:], key)
                for n in (10, 30, 60)
            },
            "torneos_registrados": len({m["torneo_id"] for m in ordered}),
            "muestra_10_partidos": len(ordered) >= 10,
            "muestra_30_partidos": len(ordered) >= 30,
            "muestra_60_partidos": len(ordered) >= 60,
        }
        profiles.append(profile)

    h2h = []
    for pair, rows in sorted(head_to_head.items()):
        a_key, b_key = pair
        a_name = names[a_key]
        b_name = names[b_key]
        a_wins = sum(
            1 for m in rows
            if (_key(m["jugador_a"]) == a_key and m["sets_a"] > m["sets_b"])
            or (_key(m["jugador_b"]) == a_key and m["sets_b"] > m["sets_a"])
        )
        h2h.append({
            "jugador_a": a_name,
            "jugador_b": b_name,
            "partidos": len(rows),
            "victorias_a": a_wins,
            "victorias_b": len(rows) - a_wins,
        })

    return {
        "resumen": {
            "snapshots_procesados": len(snapshots),
            "partidos_unicos_completos": len(matches),
            "jugadores_con_partidos": len(profiles),
            "enfrentamientos_directos": len(h2h),
        },
        "jugadores": profiles,
        "h2h": h2h,
        "partidos": matches,
        "criterios": [
            "Solo marcadores completos 3:0, 3:1 y 3:2 con confirmación recíproca.",
            "Los snapshots repetidos no duplican el mismo partido dentro de un torneo y grupo.",
            "Las ventanas 10/30/60 se calculan por orden de primera captura completa observada.",
            "Las métricas describen resultados; no prueban estados psicológicos ni causalidad.",
            "El histórico disponible depende del periodo y la frecuencia de captura de la base.",
        ],
    }


def analizar_perfiles_guardados(db):
    return construir_perfiles(db.listar_snapshots())


if __name__ == "__main__":
    import json
    from pathlib import Path
    from db import HistoryDB

    report = construir_perfiles(HistoryDB().listar_snapshots())
    Path("salida").mkdir(exist_ok=True)
    path = Path("salida/perfiles_jugadores.json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["resumen"], ensure_ascii=False))
    print(f"Informe generado: {path}")
