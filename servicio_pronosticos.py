"""Servicio de lectura, análisis y liquidación para el bot de Telegram."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from db import HistoryDB
from historial_rendimiento import acumular_historial_presion
from motor_pronosticos import pronosticar_partido
from perfil_jugadores import construir_perfiles
from radar_necesidad import acumular_radar_necesidad, clasificar_necesidad
from retroalimentacion import PredictionFeedback


def cargar_estado(db=None):
    db = db or HistoryDB()
    snapshots = db.listar_snapshots()
    latest = {}
    for snap in snapshots:
        tid = str(snap.get("tournament_id") or "")
        if tid:
            latest[tid] = snap
    tournaments = {}
    for tid, snap in latest.items():
        payload = snap.get("payload") or {}
        tournament = payload.get("torneo") if isinstance(payload.get("torneo"), dict) else payload
        tournaments[tid] = tournament
    return db, snapshots, tournaments


def listar_calendario(tournaments):
    rows = []
    for tid, tournament in tournaments.items():
        games = list(tournament.get("partidos_programados") or [])
        games.extend(tournament.get("partidos_en_vivo") or [])
        if not games:
            games = [
                p for p in tournament.get("partidos") or []
                if str(p.get("estado") or "").casefold() in {"planned", "upcoming", "live"}
            ]
        seen = set()
        for game in games:
            identity = (str(game.get("grupo") or ""), str(game.get("orden") or ""),
                        str(game.get("jugador_a") or ""), str(game.get("jugador_b") or ""),
                        str(game.get("hora") or ""))
            if identity in seen:
                continue
            seen.add(identity)
            rows.append({
                **game,
                "torneo_id": tid,
                "grupo": game.get("grupo"),
                "estado": str(game.get("estado") or "unknown").casefold(),
            })
    return rows


def _contexto_competitivo(game, tournament, snapshots):
    context = {"necesidad_actual": {}, "respuesta_historica_necesidad": {}, "rendimiento_relevante": {}}
    group_no = game.get("grupo")
    groups = tournament.get("grupos") or []
    try:
        group = groups[int(group_no) - 1] if group_no is not None else []
    except (ValueError, IndexError, TypeError):
        group = []
    names = {str(p.get("jugador") or "").strip().casefold(): i for i, p in enumerate(group)}
    a, b = str(game.get("jugador_a") or "").strip(), str(game.get("jugador_b") or "").strip()
    if a.casefold() in names and b.casefold() in names:
        context["necesidad_actual"] = clasificar_necesidad(group, names[a.casefold()], names[b.casefold()])
    need_rows = acumular_radar_necesidad(snapshots).get("jugadores", [])
    pressure_rows = acumular_historial_presion(snapshots).get("jugadores", [])
    for name in (a, b):
        key = name.casefold()
        need = next((r for r in need_rows if str(r.get("jugador") or "").casefold() == key), None)
        pressure = next((r for r in pressure_rows if str(r.get("jugador") or "").casefold() == key), None)
        if need:
            context["respuesta_historica_necesidad"][name] = {k: need.get(k) for k in ("partidos_obligado_a_ganar", "victorias_obligado", "derrotas_obligado", "respuesta_cuando_obligado", "muestra_suficiente")}
        if pressure:
            context["rendimiento_relevante"][name] = {k: pressure.get(k) for k in ("partidos_relevantes", "victorias", "derrotas", "tasa_victoria", "muestra_suficiente")}
    return context


def analizar_calendario(db=None):
    db, snapshots, tournaments = cargar_estado(db)
    feedback = PredictionFeedback(db)
    liquidacion = feedback.settle_from_snapshots(snapshots)
    calendar = listar_calendario(tournaments)
    reports = []
    now = datetime.now(timezone.utc).isoformat()
    for game in calendar:
        if game["estado"] not in {"planned", "upcoming"}:
            continue
        date_value = game.get("scheduled_at") or game.get("fecha")
        if not date_value:
            forecast = {
                "elegible": False,
                "motivo": "fecha_hora_con_zona_horaria_no_publicada",
                "detalle": "La ficha extraída solo aporta hora local sin fecha/zona horaria verificable; no se inventa el momento del partido.",
            }
        else:
            forecast = pronosticar_partido(
                snapshots,
                game.get("jugador_a"),
                game.get("jugador_b"),
                fecha_partido=date_value,
                estado=game["estado"],
            )
        if forecast.get("elegible"):
            feedback.record(game, forecast, predicted_at=now)
        context = _contexto_competitivo(game, tournaments.get(str(game.get("torneo_id")), {}), snapshots)
        reports.append({"partido": game, "pronostico": forecast, "contexto": context})
    return {
        "torneos": len(tournaments),
        "partidos_calendario": len(calendar),
        "partidos_programados_analizados": len(reports),
        "pronosticos_registrados": sum(x["pronostico"].get("elegible", False) for x in reports),
        "liquidacion": liquidacion,
        "partidos": reports,
    }


def informes(db=None):
    db, snapshots, tournaments = cargar_estado(db)
    feedback = PredictionFeedback(db)
    return {
        "torneos": len(tournaments),
        "snapshots": len(snapshots),
        "jugadores": construir_perfiles(snapshots),
        "necesidad": acumular_radar_necesidad(snapshots),
        "rendimiento": acumular_historial_presion(snapshots),
        "evaluacion": feedback.metrics(),
    }


def buscar_jugador(nombre, db=None):
    data = informes(db)
    needle = " ".join(str(nombre or "").split()).casefold()
    if not needle:
        return None
    players = data["jugadores"]["jugadores"]
    exact = [p for p in players if p["jugador"].casefold() == needle]
    matches = exact or [p for p in players if needle in p["jugador"].casefold()]
    if not matches:
        return None
    return matches[:5]


def buscar_h2h(nombre_a, nombre_b, db=None):
    data = informes(db)
    keys = {" ".join(nombre_a.split()).casefold(), " ".join(nombre_b.split()).casefold()}
    if len(keys) != 2:
        return None
    for row in data["jugadores"]["h2h"]:
        if {row["jugador_a"].casefold(), row["jugador_b"].casefold()} == keys:
            return row
    return None


def buscar_necesidad(nombre, db=None):
    data = informes(db)["necesidad"]["jugadores"]
    needle = " ".join(str(nombre or "").split()).casefold()
    rows = [row for row in data if needle in row["jugador"].casefold()] if needle else []
    return rows[:5]


def buscar_rendimiento(nombre, db=None):
    data = informes(db)["rendimiento"]["jugadores"]
    needle = " ".join(str(nombre or "").split()).casefold()
    rows = [row for row in data if needle in row["jugador"].casefold()] if needle else []
    return rows[:5]
