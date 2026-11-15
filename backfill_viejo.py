import asyncio, json
from playwright.async_api import async_playwright
from datetime import datetime

async def main():
    todos = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-blink-features=AutomationControlled'])
        page = await browser.new_page(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15")
        # Intentamos 2 URLs
        for url in ["https://m.flashscore.com/table-tennis/czech-republic/czech-liga-pro/results/", "https://www.flashscore.com/table-tennis/czech-republic/czech-liga-pro/results/"]:
            print(f"Probando {url}")
            try:
                await page.goto(url, timeout=60000)
                await page.wait_for_timeout(8000)
                titulo = await page.title()
                print(f"Titulo: {titulo}")
                html = await page.content()
                print(f"HTML: {len(html)}")
                for i in range(10):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1500)
                texto_completo = await page.inner_text("body")
                print(f"Texto pagina: {len(texto_completo)} chars")
                print("MUESTRA:", texto_completo[:800].replace("\n"," | "))
                if "Liga Pro" in texto_completo or "Proksa" in texto_completo or len(texto_completo)>5000:
                    print("¡ESTA URL SIRVIO!")
                    break
            except Exception as e:
                print(f"Fallo {url}: {e}")
        await browser.close()
    print("FIN PRUEBA - mandale foto a tu asistente")

if __name__ == "__main__":
    asyncio.run(main())
