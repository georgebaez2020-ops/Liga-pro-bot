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


def _tabla_ordenada(names, points, wins, losses, sets_for, sets_against,
                    game_points_for, game_points_against, h2h):
    """Ordena con los desempates oficiales; no inventa los puntos de juego."""
    rows = []
    for name in names:
        gp_for, gp_against = game_points_for[name], game_points_against[name]
        rows.append({
            "jugador": name, "puntos": points[name], "victorias": wins[name],
            "derrotas": losses[name], "sets_favor": sets_for[name],
            "sets_contra": sets_against[name],
            "diferencia_sets": sets_for[name] - sets_against[name],
            "puntos_juego_favor": gp_for,
            "puntos_juego_contra": gp_against,
            "diferencia_puntos_juego": (
                gp_for - gp_against if gp_for is not None and gp_against is not None else None
            ),
        })

    # Criterios oficiales en orden: puntos de partido, sets ganados,
    # diferencia de sets, diferencia de puntos de juego, puntos de juego ganados,
    # H2H solo si quedan exactamente dos empatados, y finalmente sorteo.
    def key(row):
        return (row["puntos"], row["sets_favor"], row["diferencia_sets"])

    rows.sort(key=lambda r: (-r["puntos"], -r["sets_favor"],
                             -r["diferencia_sets"], r["jugador"].casefold()))
    unresolved = []
    i = 0
    while i < len(rows):
        j = i + 1
        while j < len(rows) and key(rows[j]) == key(rows[i]):
            j += 1
        tied = rows[i:j]
        if len(tied) > 1:
            # No se puede saltar a H2H mientras falten los criterios de puntos.
            point_data_complete = all(
                row["diferencia_puntos_juego"] is not None and
                row["puntos_juego_favor"] is not None for row in tied
            )
            if point_data_complete:
                tied.sort(key=lambda r: (
                    -r["diferencia_puntos_juego"], -r["puntos_juego_favor"],
                    r["jugador"].casefold()
                ))
                k = 0
                while k < len(tied):
                    m = k + 1
                    while m < len(tied) and (
                        tied[m]["diferencia_puntos_juego"] == tied[k]["diferencia_puntos_juego"]
                        and tied[m]["puntos_juego_favor"] == tied[k]["puntos_juego_favor"]
                    ):
                        m += 1
                    exact_tie = tied[k:m]
                    if len(exact_tie) == 2:
                        result = h2h.get(frozenset((exact_tie[0]["jugador"], exact_tie[1]["jugador"])))
                        if result == exact_tie[1]["jugador"]:
                            exact_tie.reverse()
                    elif len(exact_tie) > 1:
                        unresolved.append({
                            "jugadores": [r["jugador"] for r in exact_tie],
                            "motivo": "empate tras puntos de juego; el H2H solo aplica a dos jugadores",
                            "desempate_final": "sorteo",
                        })
                    tied[k:m] = exact_tie
                    k = m
            else:
                unresolved.append({
                    "jugadores": [r["jugador"] for r in tied],
                    "motivo": "faltan puntos de juego para aplicar los desempates oficiales antes del H2H",
                    "criterios_disponibles": ["puntos de partido", "sets ganados", "diferencia de sets"],
                    "criterios_pendientes": ["diferencia de puntos de juego", "puntos de juego ganados", "H2H si quedan dos", "sorteo"],
                })
        rows[i:j] = tied
        i = j

    for position, row in enumerate(rows, 1):
        row["puesto_provisional"] = position
    return rows, unresolved


def reconstruir_secuencia(jugadores, partidos, rating_torneo=None):
    names = [str(x).strip() for x in jugadores]
    if len(names) not in (4, 5) or len(set(names)) != len(names):
        raise ValueError("Se requieren 4 o 5 jugadores con nombres únicos")
    known = set(names)
    played, points = set(), {n: 0 for n in names}
    wins, losses = {n: 0 for n in names}, {n: 0 for n in names}
    sets_for, sets_against = {n: 0 for n in names}, {n: 0 for n in names}
    game_points_for = {n: 0 for n in names}
    game_points_against = {n: 0 for n in names}
    game_points_known = {n: True for n in names}
    h2h = {}
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
            # Simular el resultado del partido actual antes de proyectar los
            # partidos restantes. Omitir estos puntos subestima la mejor plaza
            # posible si el jugador gana y oculta necesidades reales de ganar.
            win_points = dict(before)
            win_points[player] += 2
            win_points[opponent] += 1
            win_best = _best_place(win_points, remaining, player)
            lose_points = dict(before)
            lose_points[opponent] += 2
            lose_points[player] += 1
            loss_best = _best_place(lose_points, remaining, player)
            necessity[player] = {
                "debe_ganar_por_puntos_para_seguir_en_fase": win_best <= cutoff_phase and loss_best > cutoff_phase,
                "puede_seguir_por_puntos_si_pierde": loss_best <= cutoff_phase,
                "mejor_puesto_posible_por_puntos_si_gana": win_best,
                "mejor_puesto_posible_por_puntos_si_pierde": loss_best,
                "certeza": "solo_por_puntos; desempates no proyectables sin marcadores de puntos de juego",
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
        h2h[frozenset((a, b))] = winner

        # Si una tarjeta aporta total de puntos disputados por jugador, se acumula.
        # La página pública actualmente no los incluye en el calendario; si faltan
        # en un partido, el criterio de puntos queda explícitamente no disponible.
        pa, pb = match.get("puntos_juego_a"), match.get("puntos_juego_b")
        if pa is None or pb is None:
            game_points_known[a] = game_points_known[b] = False
        else:
            game_points_for[a] += int(pa)
            game_points_against[a] += int(pb)
            game_points_for[b] += int(pb)
            game_points_against[b] += int(pa)

        gp_for = {n: game_points_for[n] if game_points_known[n] else None for n in names}
        gp_against = {n: game_points_against[n] if game_points_known[n] else None for n in names}
        table, ties = _tabla_ordenada(
            names, points, wins, losses, sets_for, sets_against,
            gp_for, gp_against, h2h
        )
        sequence.append({
            "orden": match.get("orden", idx + 1), "hora": match.get("hora"),
            "jugador_a": a, "jugador_b": b,
            "marcador_sets": f"{score[0]}:{score[1]}", "ganador": winner,
            "necesidad_antes": necessity,
            "cumplio_necesidad": {
                a: (winner == a) if necessity[a]["debe_ganar_por_puntos_para_seguir_en_fase"] else None,
                b: (winner == b) if necessity[b]["debe_ganar_por_puntos_para_seguir_en_fase"] else None,
            },
            "tabla_despues": table,
            "empates_no_resueltos": ties,
            "desempates_oficiales_disponibles": (
                ["puntos de partido", "sets ganados", "diferencia de sets"] +
                (["diferencia de puntos de juego", "puntos de juego ganados", "H2H (solo dos empatados)"]
                 if all(game_points_known.values()) else [])
            ),
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
    final_table = sequence[-1]["tabla_despues"] if sequence else []
    return {
        "metodo": "resultados oficiales ordenados por hora; 2/1 puntos; desempates oficiales hasta los datos disponibles",
        "partidos_reconstruidos": len(sequence), "partidos_esperados": expected,
        "secuencia": sequence,
        "tabla_final_reconstruida": final_table,
        "empates_finales_no_resueltos": sequence[-1]["empates_no_resueltos"] if sequence else [],
        "rating_por_jugador": ratings,
        "advertencias": warnings + ([
            "El calendario extraído aporta marcador de sets, pero no puntos anotados en cada set. Por eso no se pueden aplicar diferencia de puntos de juego, total de puntos ni H2H cuando esos criterios previos faltan."
        ] if sequence else []),
        "completa": len(sequence) == expected and not warnings,
        "clasificacion_desempates_completa": bool(sequence) and not sequence[-1]["empates_no_resueltos"],
    }

def _normalizar_tokens_nombre(nombre):
    """Normaliza nombres completos y abreviaturas, conservando marcas jr./sr."""
    import re
    tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", str(nombre or "").casefold())
    aliases = {"jr": "junior", "sr": "senior"}
    return [aliases.get(token.rstrip("."), token) for token in tokens]


def _nombre_ficha_coincide(nombre_ficha, nombre_completo):
    """Compara tokens abreviados; admite segundos nombres omitidos y marcas J-r."""
    abreviados = _normalizar_tokens_nombre(nombre_ficha)
    completos = _normalizar_tokens_nombre(nombre_completo)
    if not abreviados or len(abreviados) > len(completos):
        return False
    for abreviado, completo in zip(abreviados, completos):
        if "-" in abreviado:
            partes = abreviado.split("-", 1)
            if len(partes[0]) == 1 and len(partes[1]) == 1:
                if not (completo.startswith(partes[0]) and completo.endswith(partes[1])):
                    return False
            elif not completo.startswith(abreviado):
                return False
        elif not completo.startswith(abreviado):
            return False
    return True


def _resolver_jugador_por_rating_y_nombre(rating, nombre_ficha, ratings):
    """Resuelve ratings repetidos usando las abreviaturas de la tarjeta oficial.

    Admite nombres con segundos apellidos/nombres omitidos y sufijos jr./sr.
    Las coincidencias ambiguas se dejan sin resolver: nunca se elige al azar.
    """
    candidatos = ratings.get(str(rating), [])
    coincidentes = [
        candidato for candidato in candidatos
        if _nombre_ficha_coincide(nombre_ficha, candidato)
    ]
    if len(coincidentes) == 1:
        return coincidentes[0]
    # Conserva compatibilidad con fichas donde el rating ya es único.
    if len(candidatos) == 1:
        return candidatos[0]
    return None


def parsear_detalle_oficial(texto, grupo):
    """Lee tarjetas de partido multilínea del texto visible de la ficha oficial."""
    import re

    lines = [line.strip() for line in str(texto or "").replace("\u00a0", " ").splitlines() if line.strip()]
    # Fecha oficial publicada en la sección Group (ej. 17 Nov 2026).
    fecha_torneo = None
    meses = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
             "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    for line in lines:
        mfecha = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", line)
        if mfecha and mfecha.group(2)[:3].lower() in meses:
            from datetime import date
            try:
                fecha_torneo = date(int(mfecha.group(3)), meses[mfecha.group(2)[:3].lower()],
                                    int(mfecha.group(1))).isoformat()
                break
            except ValueError:
                pass
    ratings = {}
    for player in grupo:
        name = str(player.get("jugador") or "").strip()
        rating = str(player.get("rating") or "").strip()
        if name and rating:
            ratings.setdefault(rating, []).append(name)

    rating_data = {}
    # El bloque Players puede aparecer antes de Group o directamente antes
    # de Tournament games en fichas Upcoming sin tabla.
    try:
        p_start = next(i for i, line in enumerate(lines) if line.casefold() == "players")
        section_end = next(
            i for i in range(p_start + 1, len(lines))
            if lines[i].casefold() in {"group", "tournament games"}
        )
        section = lines[p_start + 1:section_end]
        ignored = {"#", "player", "games", "rating", "+/-", "-", "—"}
        for i, line in enumerate(section):
            if not re.fullmatch(r"\d+\s*\([^)]*\)", line):
                continue
            if i + 2 >= len(section) or not re.fullmatch(r"\d+", section[i + 1]):
                continue
            delta_text = section[i + 2]
            if re.fullmatch(r"[+-]", delta_text) and i + 3 < len(section) and re.fullmatch(r"\d+", section[i + 3]):
                delta_text += section[i + 3]
            if not re.fullmatch(r"[+-]\s*\d+", delta_text):
                continue
            # El nombre es la línea útil inmediatamente anterior a GAMES;
            # se ignoran separadores gráficos y encabezados de tabla.
            name = next(
                (section[k].strip() for k in range(i - 1, -1, -1)
                 if section[k].strip().casefold() not in ignored),
                ""
            )
            if not name:
                continue
            matching = [p for p in grupo if str(p.get("jugador") or "").strip().casefold() == name.casefold()]
            if grupo and not matching:
                continue
            canonical = matching[0]["jugador"] if matching else name
            rating = str(int(section[i + 1]))
            ratings.setdefault(rating, [])
            if canonical not in ratings[rating]:
                ratings[rating].append(canonical)
            rating_data[canonical] = {
                "rating_final": int(section[i + 1]),
                "variacion": int(re.sub(r"\s", "", delta_text)),
            }
    except StopIteration:
        pass

    try:
        start = next(i for i, line in enumerate(lines) if line.casefold() == "tournament games") + 1
    except StopIteration:
        return {"partidos": [], "fecha_torneo": fecha_torneo, "rating_por_jugador": rating_data,
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
        jugador_a = _resolver_jugador_por_rating_y_nombre(r1.group(1), name1, ratings)
        jugador_b = _resolver_jugador_por_rating_y_nombre(r2.group(1), name2, ratings)
        if not jugador_a or not jugador_b or jugador_a == jugador_b:
            warnings.append({
                "hora": hour,
                "motivo": "rating y nombre abreviado no identifican jugadores de forma única",
                "rating_a": r1.group(1), "nombre_a": name1,
                "candidatos_a": ratings.get(r1.group(1), []),
                "rating_b": r2.group(1), "nombre_b": name2,
                "candidatos_b": ratings.get(r2.group(1), []),
            })
            i = j + 4
            continue
        score = None
        puntos_sets_a, puntos_sets_b = [], []
        next_i = j + 4
        if status == "finished":
            # La tarjeta oficial organiza los datos por filas:
            # sets ganados A, puntos de cada set A, sets ganados B,
            # puntos de cada set B.
            nums = []
            markers = []
            k = j + 4
            # Algunas tarjetas oficiales insertan una marca literal "T" entre
            # los dos números del marcador (p. ej. "T 3 0" o "0 T 3").
            # Se conserva la marca sin atribuirle un significado no documentado.
            while k < len(lines) and len(nums) < 12:
                if re.fullmatch(r"\d+", lines[k]):
                    nums.append(int(lines[k]))
                    k += 1
                elif lines[k].casefold() == "t":
                    markers.append(lines[k])
                    k += 1
                else:
                    break
            parsed = False
            if nums and 0 <= nums[0] <= 3:
                sets_a = nums[0]
                for sets_b in range(0, 4):
                    nsets = sets_a + sets_b
                    needed = 2 + 2 * nsets
                    if 3 <= nsets <= 5 and len(nums) >= needed and nums[1 + nsets] == sets_b and (sets_a == 3 or sets_b == 3):
                        candidate_a = nums[1:1 + nsets]
                        candidate_b = nums[2 + nsets:2 + 2 * nsets]
                        if all(0 <= x <= 30 for x in candidate_a + candidate_b):
                            puntos_sets_a, puntos_sets_b = candidate_a, candidate_b
                            score = f"{sets_a}:{sets_b}"
                            next_i = k
                            parsed = True
                            break
            if not parsed:
                # Compatibilidad con tarjetas que solo muestran el total de sets,
                # incluyendo las que insertan una marca literal "T" entre cifras.
                if len(nums) == 2 and (nums[0] == 3 or nums[1] == 3):
                    score = f"{nums[0]}:{nums[1]}"
                    next_i = k
                else:
                    warnings.append({"hora": hour, "motivo": "partido marcado FINISHED sin marcador completo"})
        elif status == "live":
            # Un marcador parcial en vivo no se registra como resultado final.
            pass
        matches.append({
            "orden": len(matches) + 1, "hora": hour, "estado": status,
            "jugador_a": jugador_a, "jugador_b": jugador_b,
            "nombre_a_en_ficha": name1, "nombre_b_en_ficha": name2,
            "marcador_sets": score, "marcador_marca": " ".join(markers) if status == "finished" and markers else None,
            "puntos_sets_a": puntos_sets_a, "puntos_sets_b": puntos_sets_b,
            "puntos_juego_a": sum(puntos_sets_a) if puntos_sets_a else None,
            "puntos_juego_b": sum(puntos_sets_b) if puntos_sets_b else None,
            "fase": stage,
        })
        i = next_i
    return {
        "partidos": matches, "fecha_torneo": fecha_torneo, "rating_por_jugador": rating_data,
        "advertencias": warnings + ([] if fecha_torneo else [{"motivo": "no se encontró fecha oficial del torneo"}]),
        "fuente": "texto visible de la ficha oficial; emparejamiento por rating",
    }


def consolidar_partidos_torneo(analisis_cronologico, partidos_sin_grupo=None):
    """Expone el calendario oficial en una estructura común para el motor predictivo.

    Conserva el grupo y la fase de origen; no genera enfrentamientos que la web
    no haya publicado. Los ratings solo se combinan cuando identifican al jugador.
    """
    partidos = []
    ratings = {}
    for partido in partidos_sin_grupo or []:
        partidos.append({**partido, "grupo": None})
    for analisis in analisis_cronologico or []:
        numero = analisis.get("grupo")
        for partido in analisis.get("partidos_ficha", []):
            partidos.append({**partido, "grupo": numero})
        for jugador, datos in (analisis.get("rating_por_jugador") or {}).items():
            ratings[jugador] = datos
    # El orden oficial de la ficha se conserva dentro de cada grupo.
    partidos.sort(key=lambda p: (p.get("grupo") or 0, p.get("orden") or 0))
    return {
        "partidos": partidos,
        "partidos_programados": [p for p in partidos if p.get("estado") in {"planned", "upcoming"}],
        "partidos_en_vivo": [p for p in partidos if p.get("estado") == "live"],
        "partidos_finalizados": [p for p in partidos if p.get("estado") == "finished"],
        "rating_por_jugador": ratings,
        "fuente": "calendario Tournament games de la ficha oficial",
    }
