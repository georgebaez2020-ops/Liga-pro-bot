import asyncio
import logging
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv('TELEGRAM_TOKEN')


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Bot Liga Pro prendido. Escribe /test')


async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Conexion OK.')


def main():
    logging.basicConfig(level=logging.INFO)
    # Evita que los Logs de Render muestren el token dentro de las direcciones
    logging.getLogger('httpx').setLevel(logging.WARNING)
    if not TOKEN:
        print('FALTA TELEGRAM_TOKEN en Render (Environment)')
        return
    asyncio.set_event_loop(asyncio.new_event_loop())
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('test', test))
    print('Bot iniciado...')
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
