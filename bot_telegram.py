import os
import json
import time
import logging
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---------- Configuración (todo viene de Render > Environment) ----------
TOKEN = os.environ.get("TELEGRAM_TOKEN")
ODDSPAPI_KEY = os.environ.get("ODDSPAPI_KEY") or os.environ.get("ODDSPAPI_API_KEY")

BASE_URL = "https://api.oddspapi.io/v4"
CZECH_LIGA_PRO = 36349              # ID del torneo en OddsPapi
CASA_REFERENCIA = "pinnacle"        # casa de apuestas usada como referencia
UMBRAL = 0.65                       # solo pronósticos con 65% o más
ZONA = ZoneInfo("America/Bogota")   # hora de Colombia
ARCHIVO_HISTORIAL = "historial.jsonl"
CACHE_SEGUNDOS = 1800               # guarda el resultado 30 minutos

logging.basicConfig(level=logging.INFO)
_cache = {"hora": 0.0, "texto": ""}


def _hora_local(valor):
    if not valor:
        return "--:--"
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        return dt.astimezone(ZONA).strftime("%d/%m %H:%M")
    except Exception:
        return "--:--"


def _precio(nodo):
    """Saca la cuota de un resultado, si está activa."""
    try:
        p = nodo["players"]["0"]
        if p.get("active", True) and p.get("price"):
            return float(p["price"])
    except (KeyError, TypeError, ValueError):
        pass
    return None


def cuotas_ganador(partido):
    """
    Busca el mercado de ganador del partido: el que tiene exactamente
    dos resultados con cuota (uno por jugador). Devuelve
    (cuota1, cuota2, id_mercado) o None.
    """
    casas = partido.get("bookmakerOdds", {})
    casa = casas.get(CASA_REFERENCIA) or (next(iter(casas.values())) if casas else None)
    if not casa:
        return None
    for id_mercado, mercado in casa.get("markets", {}).items():
        resultados = mercado.get("outcomes", {})
        if len(resultados) != 2:
            continue
        precios = [_precio(r) for r in resultados.values()]
        if all(precios):
            # Un mercado de ganador tiene cuotas que suman ~100% al invertirlas
            suma = sum(1 / p for p in precios)
            if 1.0 <= suma <= 1.15:
                return precios[0], precios[1], id_mercado
    return None


def probabilidades(c1, c2):
    """Convierte cuotas a probabilidad justa quitando el margen de la casa."""
    p1, p2 = 1 / c1, 1 / c2
    total = p1 + p2
    return p1 / total, p2 / total


def guardar_historial(registro):
    try:
        with open(ARCHIVO_HISTORIAL, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except Exception as e:
        logging.error("No pude guardar historial: %s", e)


async def traer_pronosticos() -> str:
    if time.time() - _cache["hora"] < CACHE_SEGUNDOS and _cache["texto"]:
        return _cache["texto"]

    if not ODDSPAPI_KEY:
        return "⚠️ Falta ODDSPAPI_KEY en Render (Environment)."

    params = {
        "apiKey": 692695d0-87f8-400d-a883-251c1dd740d1,
        "tournamentIds": CZECH_LIGA_PRO,
        "bookmakers": CASA_REFERENCIA,
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.get(f"{BASE_URL}/odds-by-tournaments", params=params)
            r.raise_for_status()
            partidos = r.json()
    except Exception as e:
        logging.error("Error consultando OddsPapi: %s", e)
        return "⚠️ No pude consultar OddsPapi. Revisa los Logs en Render."

    ahora = datetime.now(timezone.utc)
    revisados = 0
    elegidos = []
    mercado_usado = None

    for p in partidos:
        # Solo partidos que aún no empiezan
        try:
            inicio = datetime.fromisoformat(p["startTime"].replace("Z", "+00:00"))
            if inicio <= ahora:
                continue
        except Exception:
            continue

        res = cuotas_ganador(p)
        if not res:
            continue
        c1, c2, mercado_usado = res
        revisados += 1
        pr1, pr2 = probabilidades(c1, c2)

        # Nombres: si la API no los trae, usa los IDs de los jugadores
        n1 = p.get("participant1Name") or f"Jugador {p.get('participant1Id')}"
        n2 = p.get("participant2Name") or f"Jugador {p.get('participant2Id')}"

        if pr1 >= UMBRAL:
            elegidos.append((inicio, n1, n2, pr1, c1))
        elif pr2 >= UMBRAL:
            elegidos.append((inicio, n2, n1, pr2, c2))
        else:
            continue

        ganador, rival, prob, cuota = elegidos[-1][1], elegidos[-1][2], elegidos[-1][3], elegidos[-1][4]
        guardar_historial({
            "fixtureId": p.get("fixtureId"),
            "inicio": p["startTime"],
            "pronostico": ganador,
            "rival": rival,
            "probabilidad": round(prob, 4),
            "cuota": cuota,
            "resultado": None,  # se llenará en una fase futura
        })

    elegidos.sort(key=lambda x: x[0])

    if not elegidos:
        texto = (
            f"Revisé {revisados} partidos y ninguno llega al {int(UMBRAL*100)}% por ahora."
        )
    else:
        lineas = [f"🏓 Pronósticos del {int(UMBRAL*100)}% o más (hora de Colombia):\n"]
        for inicio, g, rv, prob, cuota in elegidos:
            lineas.append(
                f"{_hora_local(inicio.isoformat())}  {g} vs {rv}\n"
                f"   Favorito: {g} ({prob*100:.1f}%, cuota {cuota})\n"
            )
        lineas.append(f"Partidos revisados: {revisados}")
        lineas.append(f"(mercado usado: {mercado_usado})")
        texto = "\n".join(lineas)

    # Telegram permite 4096 caracteres por mensaje
    texto = texto[:4000]
    _cache["hora"] = time.time()
    _cache["texto"] = texto
    return texto


# ---------- Comandos ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Bot Liga Pro prendido. Escríbeme /test o /pronosticos"
    )


async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Conexión OK.")


async def pronosticos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Calculando probabilidades...")
    await update.message.reply_text(await traer_pronosticos())


def main():
    if not TOKEN:
        print("FALTA TELEGRAM_TOKEN en Render")
        return
    asyncio.set_event_loop(asyncio.new_event_loop())
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("pronosticos", pronosticos))
    print("Bot iniciado...")
    app.run_polling()


if __name__ == "__main__":
    main()
