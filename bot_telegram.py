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


def _json_file(path, default):
    import json
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _save_json(path, data):
    import json
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def _registrar_chat(chat_id):
    path = os.getenv("TELEGRAM_CHATS_FILE", "salida/telegram_chats.json")
    chats = _json_file(path, [])
    chat_id = str(chat_id)
    if chat_id not in chats:
        chats.append(chat_id)
        _save_json(path, chats)


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


async def _notificar_cambios_torneos(context, tournaments):
    """Notifica torneos nuevos LIVE/UPCOMING y transiciones UPCOMING -> LIVE."""
    state_path = os.getenv("TELEGRAM_TOURNAMENT_STATE_FILE", "salida/telegram_tournaments_state.json")
    current = {
        str(tid): str(data.get("estado") or "unknown").casefold()
        for tid, data in tournaments.items()
    }
    previous = _json_file(state_path, None)
    # Primera ejecución: establece una línea base sin enviar avisos antiguos.
    if previous is None:
        _save_json(state_path, current)
        logging.info("Línea base de notificaciones de torneos creada.")
        return
    chats = _json_file(os.getenv("TELEGRAM_CHATS_FILE", "salida/telegram_chats.json"), [])
    changes = [
        (tid, status) for tid, status in current.items()
        if status in {"live", "upcoming"} and previous.get(tid, "absent") != status
    ]
    # Si todavía nadie ha iniciado el bot, conserva el estado anterior para
    # que los avisos pendientes puedan enviarse después de /start.
    if changes and not chats:
        logging.info("Hay cambios de torneos, pero aún no hay chats suscritos.")
        return
    failed = set()
    for tid, status in changes:
        label = "🔴 TORNEO EN VIVO" if status == "live" else "🗓️ NUEVO TORNEO PRÓXIMO"
        date = tournaments[tid].get("fecha_torneo") or "fecha no publicada"
        message = f"{label}\nTorneo #{tid}\nFecha: {date}\nhttps://tt.league-pro.com/en/tournaments/{tid}"
        for chat_id in chats:
            try:
                await context.bot.send_message(chat_id=int(chat_id), text=message, disable_web_page_preview=True)
            except Exception:
                failed.add(tid)
                logging.exception("No se pudo enviar aviso del torneo %s al chat %s.", tid, chat_id)
    # No marca como notificado lo que falló: se reintentará en el siguiente ciclo.
    updated = dict(current)
    for tid in failed:
        if tid in previous:
            updated[tid] = previous[tid]
        else:
            updated.pop(tid, None)
    _save_json(state_path, updated)


def _chunks(text, limit=3900):
    text = str(text)
    return [text[i:i + limit] for i in range(0, len(text), limit)] or ["Sin datos disponibles."]


async def _reply(update, text):
    for chunk in _chunks(text):
        await update.effective_message.reply_text(chunk)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _registrar_chat(update.effective_chat.id)
    await _reply(update,
        "🏓 Liga Pro Bot conectado.\n\n"
        "Comandos:\n"
        "/estado — estado de la memoria y torneos\n"
        "/calendario — partidos programados y en vivo\n"
        "/torneos — torneos en vivo y próximos\n"
        "/vivo — torneos que están en juego\n"
        "/proximos — torneos próximos\n"
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
                    _, _, tournaments = cargar_estado()
                    await _notificar_cambios_torneos(context, tournaments)
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
