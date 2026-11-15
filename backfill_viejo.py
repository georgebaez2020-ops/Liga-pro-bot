import asyncio, json
from playwright.async_api import async_playwright
from datetime import datetime

async def main():
    todos = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36")
        url = "https://www.flashscore.com/table-tennis/czech-republic/czech-liga-pro/results/"
        print(f"Jalando 12 meses de {url}")
        await page.goto(url, timeout=60000)
        await page.wait_for_timeout(8000)
        # Intentar aceptar cookies si aparece
        try:
            await page.get_by_text("Accept").first.click(timeout=3000)
        except:
            pass
        for i in range(20):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)
            print(f"Cargando... vuelta {i+1}/20")
        # Probar varios selectores
        html = await page.content()
        print(f"HTML largo: {len(html)} caracteres")
        # Guardar muestra para debug
        with open("debug.html","w") as f: f.write(html[:5000])
        # Selector nuevo de Flashscore 2026
        elementos = await page.query_selector_all("div[class*='event__match'], div[class*='eventRow'], a[class*='eventRow']")
        print(f"Intento 1: {len(elementos)}")
        if len(elementos)==0:
            elementos = await page.query_selector_all("[id*='g_']")
            print(f"Intento 2 por ID: {len(elementos)}")
        for el in elementos:
            try:
                texto = await el.inner_text()
                if len(texto.strip())>5:
                    todos.append({"texto": texto.replace("\n", " | "), "fecha_scrape": str(datetime.now()), "fuente": "flashscore_12m"})
            except:
                continue
        await browser.close()
    try:
        with open("liga_pro_db.json") as f: db = json.load(f)
    except: db = {"jugadores": {}, "partidos": [], "tabla": {}}
    existentes = set([p["texto"] for p in db["partidos"]])
    nuevos = 0
    for p in todos:
        if p["texto"] not in existentes:
            db["partidos"].append(p)
            nuevos += 1
    with open("liga_pro_db.json", "w") as f: json.dump(db, f, indent=2)
    print(f"LISTO 12 MESES: {nuevos} partidos guardados. Total: {len(db['partidos'])}")
    for t in todos[:5]:
        print("EJEMPLO:", t["texto"][:150])

if __name__ == "__main__":
    asyncio.run(main())
