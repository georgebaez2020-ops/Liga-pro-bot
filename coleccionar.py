import json, os, time
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

def coleccionar_ventana(fecha_inicio_str, fecha_fin_str, archivo_salida):
    inicio = datetime.strptime(fecha_inicio_str, "%Y-%m-%d")
    fin = datetime.strptime(fecha_fin_str, "%Y-%m-%d")

    todos = []
    if os.path.exists(archivo_salida):
        try:
            with open(archivo_salida) as f:
                todos = json.load(f)
        except:
            todos = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Linux; Android 10; Pixel 4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36",
            viewport={"width": 390, "height": 844}
        )
        page = context.new_page()

        dia = inicio
        while dia <= fin:
            fecha_str = dia.strftime("%Y-%m-%d")
            try:
                # URL MOVIL REAL que me pasaste
                url = "https://m.aiscore.com/es/table-tennis"
                print(f"Abriendo {fecha_str} -> {url}")
                page.goto(url, timeout=30000)
                page.wait_for_timeout(8000)
                
                contenido = page.content()
                print(f"{fecha_str}: len={len(contenido)}")
                
                # Guardamos para ver si ya paso Cloudflare
                with open(f"debug_{fecha_str}.html", "w", encoding="utf-8") as f:
                    f.write(contenido)
                print(f"{fecha_str}: guardado debug")

            except Exception as e:
                print(f"{fecha_str}: fallo, sigo - {e}")
            
            dia += timedelta(days=1)
            time.sleep(3)

        browser.close()

    print(f"LISTO. Total guardado: {len(todos)}")

if __name__ == "__main__":
    # SOLO 1 DIA DE PRUEBA, no los 8 meses todavia
    coleccionar_ventana("2026-03-17", "2026-03-17", "tablas.json")
