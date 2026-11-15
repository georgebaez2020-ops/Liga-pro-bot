import os
import requests

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send(msg):
    if not TOKEN or not CHAT_ID:
        print("Faltan secrets de Telegram")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg})

if __name__ == "__main__":
    print("Scraper corriendo...")
    send("✅ Test Liga Pro Bot: el workflow ya funciona en GitHub Actions")
    print("Listo")
