"""Interfaz Telegram del Liga Pro Bot; el scraper corre automáticamente cada 15 min."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from servicio_pronosticos import (
    analizar_calendario, buscar_h2h, buscar_jugador, cargar_estado, informes,
    listar_calendario, buscar_necesidad, buscar_rendimiento,
)

TOKEN = os.getenv("TELEGRAM_TOKEN")
SCRAPE_INTERVAL = max(300, int(os.getenv("SCRAPE_INTERVAL_SECONDS", "900")))
_scrape_lock = asyncio.Lock()


def _torneos_por_estado(tournaments, wanted):
    return [
        (str(tid), data) for tid, data in tournaments.items()
        if str(data.get("estado") or "unknown").casefold() in wanted
    ]


def _formatear_torneos(tournaments, wanted, heading):
    rows = _torneos_por_estado(tournaments, wanted)
    if not rows:
        return heading + "\nNo hay torneos en esta categoría en la última actualización."
    lines = [heading, f"Total: {len(rows)}"]
    for tid, data in sorted(rows, key=lambda item: (str(item[1].get("fecha_torneo") or ""), item[0])):
        status = str(data.get("estado") or "unknown").upper()
        date = data.get("fecha_torneo") or "fecha no publicada"
        lines.append(f"\n🏓 Torneo #{tid} — {status}\nFecha: {date}\nhttps://tt.league-pro.com/en/tournaments/{tid}")
    return "\n".join(lines)




def _chunks(text, limit=3900):
    text = str(text)
    return [text[i:i + limit] for i in range(0, len(text), limit)] or ["Sin datos disponibles."]


async def _reply(update, text):
    for chunk in _chunks(text):
        await update.effective_message.reply_text(chunk)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update,
        "🏓 Liga Pro Bot conectado.\n\n"
        "Comandos:\n"
        "/estado — estado de la memoria y torneos\n"
        "/calendario — partidos programados y en vivo\n"
        "/torneos — torneos en vivo y próximos\n"
        "/vivo — torneos que están en directo\n"
        "/proximos — torneos próximos\n"
        "/torneo NUMERO — partidos y desarrollo de un torneo\n"
        "/tabla NUMERO — clasificación por grupos del torneo\n"
        "/pronosticos — análisis conservador de próximos partidos\n"
        "/jugador NOMBRE — histórico de un jugador\n"
        "/necesidad NOMBRE — respuesta histórica cuando debía ganar\n"
        "/rendimiento NOMBRE — partidos competitivamente relevantes\n"
        "/h2h JUGADOR 1 | JUGADOR 2 — enfrentamientos directos\n"
        "/evaluacion — métricas de aciertos y calibración\n"
        "/test — comprobar conexión")


async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, "Conexión Telegram OK. 🟢")


async def estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        db, snapshots, tournaments = cargar_estado()
        counts = {"live": 0, "upcoming": 0, "finished": 0, "unknown": 0}
        for tournament in tournaments.values():
            key = str(tournament.get("estado") or "unknown").casefold()
            counts[key] = counts.get(key, 0) + 1
        await _reply(update,
            f"📊 MEMORIA LIGA PRO\nTorneos: {len(tournaments)}\n"
            f"Snapshots: {len(snapshots)}\n"
            f"En vivo: {counts.get('live', 0)} | Programados: {counts.get('upcoming', 0)} | "
            f"Finalizados: {counts.get('finished', 0)}\n"
            f"Base de datos: {db.kind}")
    except Exception as exc:
        logging.exception("Error en /estado")
        await _reply(update, f"No pude leer la memoria: {type(exc).__name__}: {exc}")


async def calendario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        _, _, tournaments = cargar_estado()
        games = listar_calendario(tournaments)
        if not games:
            await _reply(update, "No hay partidos programados o en vivo guardados. El scraper actualizará los datos automáticamente.")
            return
        lines = ["🗓️ CALENDARIO OFICIAL"]
        for game in games[:35]:
            a, b = game.get("jugador_a", "?"), game.get("jugador_b", "?")
            hora_co = game.get("hora_colombia") or "—"
            hora_pr = game.get("hora_praga") or game.get("hora") or "—"
            lines.append(f"• {game.get('estado','?').upper()} | {a} vs {b} | Grupo {game.get('grupo') or '—'} | Colombia {hora_co} | Praga {hora_pr}")
        await _reply(update, "\n".join(lines))
    except Exception as exc:
        logging.exception("Error en /calendario")
        await _reply(update, f"Error consultando calendario: {type(exc).__name__}: {exc}")


async def torneos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        _, _, tournaments = cargar_estado()
        await _reply(update, _formatear_torneos(tournaments, {"live", "upcoming"}, "🏓 TORNEOS LIVE Y PRÓXIMOS"))
    except Exception as exc:
        logging.exception("Error en /torneos")
        await _reply(update, f"Error consultando torneos: {type(exc).__name__}: {exc}")


async def vivo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        _, _, tournaments = cargar_estado()
        await _reply(update, _formatear_torneos(tournaments, {"live"}, "🔴 TORNEOS EN VIVO"))
    except Exception as exc:
        logging.exception("Error en /vivo")
        await _reply(update, f"Error consultando torneos en vivo: {type(exc).__name__}: {exc}")


async def proximos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        _, _, tournaments = cargar_estado()
        await _reply(update, _formatear_torneos(tournaments, {"upcoming"}, "🗓️ PRÓXIMOS TORNEOS"))
    except Exception as exc:
        logging.exception("Error en /proximos")
        await _reply(update, f"Error consultando próximos torneos: {type(exc).__name__}: {exc}")


def _tabla_grupo_texto(analisis):
    reconstruction = analisis.get("reconstruccion") or {}
    sequence = reconstruction.get("secuencia") or []
    table = sequence[-1].get("tabla_despues") if sequence else reconstruction.get("tabla_final_reconstruida")
    if not table:
        return "Tabla todavía sin resultados finalizados."
    lines = ["Pos | Jugador | PJ | G | P | Pts"]
    for position, row in enumerate(table, 1):
        played = int(row.get("victorias", 0)) + int(row.get("derrotas", 0))
        lines.append(
            f"{position}. {row.get('jugador', '?')} | {played} | "
            f"{row.get('victorias', 0)} | {row.get('derrotas', 0)} | {row.get('puntos', 0)}"
        )
    if reconstruction.get("empates_finales_no_resueltos"):
        lines.append("⚠️ Hay empates que requieren criterios oficiales adicionales.")
    return "\n".join(lines)


def _detalle_torneo(tid, tournament):
    status = str(tournament.get("estado") or "unknown").upper()
    lines = [
        f"🏓 TORNEO #{tid} — {status}",
        f"Fecha: {tournament.get('fecha_torneo') or 'no publicada'}",
        f"Ficha oficial: https://tt.league-pro.com/en/tournaments/{tid}",
    ]
    matches = tournament.get("partidos") or []
    live = [m for m in matches if m.get("estado") == "live"]
    upcoming = [m for m in matches if m.get("estado") in {"planned", "upcoming"}]
    finished = [m for m in matches if m.get("estado") == "finished"]
    lines.append(
        f"\n📊 PARTIDOS: 🔴 {len(live)} en vivo | ⏳ {len(upcoming)} pendientes | "
        f"✅ {len(finished)} finalizados"
    )
    if live:
        lines.append("\n🔴 PARTIDOS EN VIVO")
        for match in live:
            parcial = match.get("marcador_live_sets")
            detalle_parcial = (
                f" | sets: {parcial}"
                if parcial is not None else " | marcador parcial no disponible en la ficha"
            )
            lines.append(
                f"• {match.get('jugador_a', '?')} vs {match.get('jugador_b', '?')} "
                f"| Grupo {match.get('grupo') or '—'}{detalle_parcial}"
            )
    if upcoming:
        lines.append("\n⏳ PRÓXIMOS PARTIDOS")
        for match in upcoming[:20]:
            lines.append(
                f"• {match.get('hora_colombia') or match.get('hora') or 'Hora —'} | "
                f"{match.get('jugador_a', '?')} vs {match.get('jugador_b', '?')} "
                f"| Grupo {match.get('grupo') or '—'}"
            )
    if finished:
        lines.append("\n✅ ÚLTIMOS RESULTADOS")
        for match in finished[-20:]:
            lines.append(
                f"• {match.get('jugador_a', '?')} {match.get('marcador_sets') or '?'} "
                f"{match.get('jugador_b', '?')} | Grupo {match.get('grupo') or '—'}"
            )
    analyses = tournament.get("analisis_cronologico") or []
    for analysis in analyses:
        number = analysis.get("grupo", "?")
        lines.append(f"\n📋 TABLA — GRUPO {number}")
        lines.append(_tabla_grupo_texto(analysis))
    if not analyses and tournament.get("grupos"):
        lines.append("\nLa ficha tiene jugadores, pero todavía no hay una tabla reconstruible.")
        for number, group in enumerate(tournament.get("grupos") or [], 1):
            lines.append(f"Grupo {number}: " + ", ".join(p.get("jugador", "?") for p in group))
    if not matches and not tournament.get("grupos"):
        lines.append("\nLa ficha todavía no publica partidos ni grupos.")
    return "\n".join(lines)


async def torneo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await _reply(update, "Uso: /torneo ID\nEjemplo: /torneo 123456")
        return
    tid = context.args[0].strip().rstrip("/").split("/")[-1]
    try:
        _, _, tournaments = cargar_estado()
        tournament = tournaments.get(tid)
        if not tournament:
            await _reply(update, f"No encuentro el torneo #{tid} en la última extracción. Revisa /vivo o /proximos y vuelve a intentarlo.")
            return
        await _reply(update, _detalle_torneo(tid, tournament))
    except Exception as exc:
        logging.exception("Error consultando detalle del torneo %s", tid)
        await _reply(update, f"Error consultando torneo: {type(exc).__name__}: {exc}")


async def tabla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra exclusivamente la clasificación por grupos de un torneo."""
    if not context.args:
        await _reply(
            update,
            "Uso: /tabla NUMERO\\nEjemplo: /tabla 38185\\n"
            "Puedes copiar el número desde /vivo o /proximos."
        )
        return

    tid = context.args[0].strip().rstrip("/").split("/")[-1]
    if not tid.isdigit():
        await _reply(update, "El identificador debe ser numérico. Ejemplo: /tabla 38185")
        return

    try:
        _, _, tournaments = cargar_estado()
        tournament = tournaments.get(tid)
        if not tournament:
            await _reply(
                update,
                f"No encuentro el torneo #{tid} en la última extracción. "
                "Consulta /vivo o /proximos para obtener un identificador vigente."
            )
            return

        lines = [
            f"📊 TABLAS DEL TORNEO #{tid}",
            f"Estado: {str(tournament.get('estado') or 'unknown').upper()}",
            f"Fecha: {tournament.get('fecha_torneo') or 'no publicada'}",
            f"Ficha oficial: https://tt.league-pro.com/en/tournaments/{tid}",
        ]
        analyses = tournament.get("analisis_cronologico") or []
        if analyses:
            for analysis in analyses:
                lines.append(f"\\n📋 GRUPO {analysis.get('grupo', '?')}")
                lines.append(_tabla_grupo_texto(analysis))
        else:
            groups = tournament.get("grupos") or []
            if groups:
                for number, group in enumerate(groups, 1):
                    lines.append(f"\\n📋 GRUPO {number}")
                    lines.append("Tabla todavía sin resultados finalizados.")
                    names = [str(player.get("jugador") or "?") for player in group]
                    if names:
                        lines.append("Jugadores: " + ", ".join(names))
            else:
                lines.append(
                    "\\nLa ficha oficial todavía no publica grupos ni una tabla de clasificación. "
                    "En los torneos próximos puede que la clasificación aún no esté disponible."
                )

        lines.append(
            "\\nNota: la clasificación se reconstruye con partidos finalizados; "
            "los encuentros LIVE o pendientes no suman puntos."
        )
        await _reply(update, "\\n".join(lines))
    except Exception as exc:
        logging.exception("Error consultando tabla del torneo %s", tid)
        await _reply(update, f"Error consultando tabla: {type(exc).__name__}: {exc}")


async def pronosticos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result = analizar_calendario()
        lines = [
            "🧠 ANÁLISIS DE PRÓXIMOS PARTIDOS",
            f"Partidos programados: {result['partidos_programados_analizados']}",
            f"Pronósticos elegibles registrados: {result['pronosticos_registrados']}",
            f"Resultados liquidados ahora: {result['liquidacion']['liquidados']}",
        ]
        for item in result["partidos"][:25]:
            game, forecast = item["partido"], item["pronostico"]
            pair = f"{game.get('jugador_a','?')} vs {game.get('jugador_b','?')}"
            if forecast.get("elegible"):
                lines.append(f"✅ {pair}: {forecast['favorito']} ({forecast['probabilidad_a']}% / {forecast['probabilidad_b']}%). Confianza {forecast['nivel_confianza']}.")
            else:
                lines.append(f"⏸️ {pair}: sin pronóstico — {forecast.get('motivo','no elegible')}.")
            if forecast.get("elegible"):
                lines.append(
                    f"   Forma últimos 10: {forecast.get('jugador_a')} "
                    f"{forecast.get('forma_ultimos_10_a', {}).get('victorias', 0)}/"
                    f"{forecast.get('forma_ultimos_10_a', {}).get('partidos', 0)} — "
                    f"{forecast.get('jugador_b')} "
                    f"{forecast.get('forma_ultimos_10_b', {}).get('victorias', 0)}/"
                    f"{forecast.get('forma_ultimos_10_b', {}).get('partidos', 0)}"
                )
            context = item.get("contexto") or {}
            for player, detail in context.get("necesidad_actual", {}).items():
                lines.append(f"   Necesidad actual {player}: {detail.get('necesidad_fase_final', 'sin dato')}.")
            for player, detail in context.get("respuesta_historica_necesidad", {}).items():
                sample = detail.get("partidos_obligado_a_ganar", 0)
                if sample:
                    lines.append(f"   Historial obligado {player}: {detail.get('victorias_obligado', 0)}V/{detail.get('derrotas_obligado', 0)}D en {sample} partidos.")
            for player, detail in context.get("rendimiento_relevante", {}).items():
                sample = detail.get("partidos_relevantes", 0)
                if sample:
                    lines.append(f"   Partidos relevantes {player}: {detail.get('victorias', 0)}V/{detail.get('derrotas', 0)}D en {sample} partidos.")
        lines.append("\nEl bot se abstiene si falta histórico suficiente o una fecha/hora verificable.")
        await _reply(update, "\n".join(lines))
    except Exception as exc:
        logging.exception("Error en /pronosticos")
        await _reply(update, f"Error calculando pronósticos: {type(exc).__name__}: {exc}")


async def jugador(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = " ".join(context.args).strip()
    if not name:
        await _reply(update, "Uso: /jugador Nombre Apellido")
        return
    try:
        rows = buscar_jugador(name)
        if not rows:
            await _reply(update, f"No encuentro histórico para «{name}».")
            return
        lines = ["📈 HISTÓRICO DE JUGADOR"]
        for p in rows:
            g = p["global"]
            lines.append(
                f"{p['jugador']}\nPartidos: {g['partidos']} | Victorias: {g['victorias']} | "
                f"Derrotas: {g['derrotas']} | Efectividad: {g['porcentaje_victorias']}%\n"
                f"Últimos 10: {p['ventanas']['10']['victorias']}V / {p['ventanas']['10']['derrotas']}D\n"
                f"Últimos 30: {p['ventanas']['30']['victorias']}V / {p['ventanas']['30']['derrotas']}D"
            )
        await _reply(update, "\n\n".join(lines))
    except Exception as exc:
        logging.exception("Error en /jugador")
        await _reply(update, f"Error consultando jugador: {type(exc).__name__}: {exc}")



async def necesidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = " ".join(context.args).strip()
    if not name:
        await _reply(update, "Uso: /necesidad Nombre del jugador")
        return
    try:
        rows = buscar_necesidad(name)
        if not rows:
            await _reply(update, f"No hay datos de necesidad competitiva para «{name}».")
            return
        lines = ["🧭 RADAR DE NECESIDAD COMPETITIVA"]
        for row in rows:
            lines.append(
                f"{row['jugador']}\nPartidos con necesidad: {row['partidos_con_necesidad']} | "
                f"Obligado a ganar: {row['partidos_obligado_a_ganar']}\n"
                f"Victorias obligado: {row['victorias_obligado']} | "
                f"Derrotas: {row['derrotas_obligado']}\n"
                f"Respuesta: {row['respuesta_cuando_obligado']} | "
                f"Muestra suficiente: {'sí' if row['muestra_suficiente'] else 'no'}\n"
                f"{row['interpretacion']}"
            )
        await _reply(update, "\n\n".join(lines))
    except Exception as exc:
        logging.exception("Error en /necesidad")
        await _reply(update, f"Error consultando radar: {type(exc).__name__}: {exc}")


async def rendimiento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = " ".join(context.args).strip()
    if not name:
        await _reply(update, "Uso: /rendimiento Nombre del jugador")
        return
    try:
        rows = buscar_rendimiento(name)
        if not rows:
            await _reply(update, f"No hay partidos competitivamente relevantes registrados para «{name}».")
            return
        lines = ["🔥 RENDIMIENTO EN CONTEXTOS COMPETITIVOS"]
        for row in rows:
            lines.append(
                f"{row['jugador']}\nPartidos relevantes: {row['partidos_relevantes']} | "
                f"Victorias: {row['victorias']} | Derrotas: {row['derrotas']}\n"
                f"Tasa de victoria: {row['tasa_victoria']} | "
                f"Torneos con muestra: {row['torneos_con_muestra']}\n"
                f"{row['interpretacion']}"
            )
        await _reply(update, "\n\n".join(lines))
    except Exception as exc:
        logging.exception("Error en /rendimiento")
        await _reply(update, f"Error consultando rendimiento: {type(exc).__name__}: {exc}")

async def h2h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args)
    parts = [x.strip() for x in raw.split("|", 1)]
    if len(parts) != 2 or not all(parts):
        await _reply(update, "Uso: /h2h Jugador 1 | Jugador 2")
        return
    try:
        row = buscar_h2h(parts[0], parts[1])
        if not row:
            await _reply(update, "No hay enfrentamientos directos completos registrados entre esos jugadores.")
            return
        await _reply(update,
            f"⚔️ H2H: {row['jugador_a']} vs {row['jugador_b']}\n"
            f"Partidos: {row['partidos']}\n"
            f"Victorias: {row['jugador_a']} {row['victorias_a']} — "
            f"{row['jugador_b']} {row['victorias_b']}")
    except Exception as exc:
        logging.exception("Error en /h2h")
        await _reply(update, f"Error consultando H2H: {type(exc).__name__}: {exc}")


async def evaluacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from retroalimentacion import PredictionFeedback
        from db import HistoryDB
        metrics = PredictionFeedback(HistoryDB()).metrics()
        if metrics.get("muestra", 0) == 0:
            await _reply(update, "Todavía no hay pronósticos liquidados. El bot necesita registrar pronósticos previos y observar sus resultados oficiales.")
            return
        await _reply(update,
            f"🎯 EVALUACIÓN DEL MODELO\nMuestra: {metrics['muestra']}\n"
            f"Accuracy: {metrics['accuracy']:.1%}\nBrier: {metrics['brier']}\n"
            f"Log loss: {metrics['log_loss']}\nEstado: {metrics['estado']}")
    except Exception as exc:
        logging.exception("Error en /evaluacion")
        await _reply(update, f"Error consultando evaluación: {type(exc).__name__}: {exc}")


async def scrape_job(context: ContextTypes.DEFAULT_TYPE):
    if _scrape_lock.locked():
        logging.info("Se omite ciclo: ya hay una extracción en curso.")
        return
    async with _scrape_lock:
        logging.info("Iniciando actualización automática de Czech Liga Pro.")
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable, "tablas_scraper.py",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, _ = await asyncio.wait_for(process.communicate(), timeout=840)
            tail = output.decode("utf-8", errors="replace")[-6000:]
            if process.returncode:
                logging.error("Scraper terminó con código %s:\n%s", process.returncode, tail)
            else:
                logging.info("Scraper actualizado correctamente:\n%s", tail)
                try:
                    from servicio_pronosticos import analizar_calendario
                    result = analizar_calendario()
                    logging.info("Ciclo predictivo: %s partidos analizados; %s pronósticos registrados; %s resultados liquidados.",
                                 result["partidos_programados_analizados"],
                                 result["pronosticos_registrados"],
                                 result["liquidacion"]["liquidados"])
                except Exception:
                    logging.exception("Falló el ciclo predictivo posterior al scraper.")
        except asyncio.TimeoutError:
            logging.exception("Tiempo agotado en scraper.")
        except Exception:
            logging.exception("No se pudo ejecutar el scraper.")


def main():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not TOKEN:
        raise RuntimeError("Falta TELEGRAM_TOKEN en las variables de entorno.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("estado", estado))
    app.add_handler(CommandHandler("calendario", calendario))
    app.add_handler(CommandHandler("torneos", torneos))
    app.add_handler(CommandHandler("vivo", vivo))
    app.add_handler(CommandHandler("proximos", proximos))
    app.add_handler(CommandHandler("torneo", torneo))
    app.add_handler(CommandHandler("tabla", tabla))
    app.add_handler(CommandHandler("pronosticos", pronosticos))
    app.add_handler(CommandHandler("jugador", jugador))
    app.add_handler(CommandHandler("necesidad", necesidad))
    app.add_handler(CommandHandler("rendimiento", rendimiento))
    app.add_handler(CommandHandler("h2h", h2h))
    app.add_handler(CommandHandler("evaluacion", evaluacion))
    if app.job_queue is None:
        raise RuntimeError("Instala python-telegram-bot[job-queue] para activar las actualizaciones.")
    app.job_queue.run_repeating(scrape_job, interval=SCRAPE_INTERVAL, first=10, name="scrape-czech-liga-pro")
    logging.info("Liga Pro Bot listo; actualización cada %s segundos.", SCRAPE_INTERVAL)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
