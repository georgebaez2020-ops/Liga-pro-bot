import re
from playwright.sync_api import sync_playwright

def prueba():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        page = context.new_page()
        url = "https://m.aiscore.com/es/table-tennis"
        print(f"Abriendo -> {url}")
        page.goto(url, timeout=30000)
        page.wait_for_timeout(10000)

        contenido = page.content()
        print(f"len={len(contenido)}")
        print("=== PRIMEROS 3000 CARACTERES ===")
        print(contenido[:3000])
        print("=== FIN ===")

        texto = page.inner_text("body")[:3000]
        print("=== TEXTO VISIBLE ===")
        print(texto)
        print("=== FIN TEXTO ===")

        print("Tiene Cloudflare?", "Cloudflare" in contenido or "Just a moment" in contenido)
        print("Tiene table-tennis?", "table-tennis" in contenido.lower())
        print("Tiene vs?", " vs " in contenido.lower())
        print("Tiene score?", "score" in contenido.lower())

        browser.close()

if __name__ == "__main__":
    prueba()
