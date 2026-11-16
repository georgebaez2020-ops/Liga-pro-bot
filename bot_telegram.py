import os
import time
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---------- Configuración (todo viene de Render > Environment) ----------
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("CHAT_ID")
ODDSPAPI_KEY = os.environ.get("ODDSPAPI_KEY") or os.environ.get("ODDSPAPI_API_KEY")

BASE_URL = "https://api.oddspapi.io/v4"
CZECH_LIGA_PRO = 36349          # ID del torneo en OddsPapi
ZONA = ZoneInfo("Europe/Prague")  # hora local de la liga
HORAS_ENTRE_REVISIONES = 6      # 4 consultas al día = unas 120 al mes (límite: 250)
MAX_PARTIDOS = 15

logging.basicConfig(level=logging.INFO)

# Caché para no gastar consultas de más
_cache = {"hora": 0.0, "texto": ""}


def _hora_local(valor):
    """Convierte la fecha que manda OddsPapi a hora de Praga (HH:MM)."""
    if not valor:
        return "--:--"
    try:
        if isinstance(valor, (int, float)):
            dt = datetime.fromtimestamp(valor, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        return dt.astimezone(ZONA).strftime("%d/%m %H:%M")
    except Exception:
        return "--:--"


async def traer_partidos() -> str:
    """Pide a OddsPapi los partidos de la Liga Pro checa y arma el mensaje."""
    # Si la última consulta fue hace menos de 1 hora, reutiliza el resultado
    if time.time() - _cache["hora"] < 3600 and _cache["texto"]:
        return _cache["texto"]

    if not ODDSPAPI_KEY:
        return "⚠️ Falta ODDSPAPI_KEY en Render (Environment)."

    hoy = datetime.now(timezone.utc).date()
    params = {
        "apiKey": ODDSPAPI_KEY,
        "tournamentId": CZECH_LIGA_PRO,
        "from": hoy.isoformat(),
        "to": (hoy + timedelta(days=1)).isoformat(),
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{BASE_URL}/fixtures", params=params)
            r.raise_for_status()
            datos = r.json()
    except Exception as e:
        logging.error("Error consultando OddsPapi: %s", e)
        return f"⚠️ No pude consultar OddsPapi: {e}"

    partidos = [f for f in datos if f.get("hasOdds")]
    if not partidos:
        texto = "No encontré partidos con cuotas en la Liga Pro checa por ahora."
    else:
        lineas = ["🏓 Liga Pro checa, próximos partidos:\n"]
        for f in partidos[:MAX_PARTIDOS]:
            hora = _hora_local(f.get("startTime") or f.get("startDate"))
            j1 = f.get("participant1Name", "?")
            j2 = f.get("participant2Name", "?")
            lineas.append(f"{hora}  {j1} vs {j2}")
        lineas.append(f"\nTotal con cuotas: {len(partidos)}")
        texto = "\n".join(lineas)

    _cache["hora"] = time.time()
    _cache["texto"] = texto
    return texto


# ---------- Comandos ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Bot Liga Pro prendido. Escríbeme /test o /partidos"
    )


async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Conexión OK. Ya puedes seguir con el bot completo."
    )


async def partidos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Consultando partidos...")
    texto = await traer_partidos()
    await update.message.reply_text(texto)


# ---------- Tarea automática ----------
async def revision_automatica(context: ContextTypes.DEFAULT_TYPE):
    texto = await traer_partidos()
    if CHAT_ID:
        await context.bot.send_message(chat_id=CHAT_ID, text=texto)


def main():
    if not TOKEN:
        print("FALTA TELEGRAM_TOKEN en Render")
        return
    asyncio.set_event_loop(asyncio.new_event_loop())
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("partidos", partidos))

    if app.job_queue is None:
        print("Falta instalar python-telegram-bot[job-queue] en requirements.txt")
    else:
        app.job_queue.run_repeating(
            revision_automatica,
            interval=HORAS_ENTRE_REVISIONES * 3600,
            first=30,
        )

    print("Bot iniciado...")
    app.run_polling()


if __name__ == "__main__":
    main()
