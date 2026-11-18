"""Diagnostica la disponibilidad pública de las hojas de partido de League Pro.

No inicia sesión, no lee cookies y no escribe en la base histórica.
Uso:
  python inspeccionar_hoja_partido.py https://tt.league-pro.com/en/tournaments/37944/320262
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright


BASE_HOST = "tt.league-pro.com"


def validar_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != BASE_HOST:
        raise ValueError("Usa una URL HTTPS oficial de tt.league-pro.com")
    if not re.fullmatch(r"/en/tournaments/\d+/\d+/?", parsed.path):
        raise ValueError("La URL debe tener formato /en/tournaments/ID_TORNEO/ID_PARTIDO")
    return url


async def inspeccionar(url: str) -> dict:
    url = validar_url(url)
    requests_seen = []
    responses_seen = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.on("request", lambda req: requests_seen.append({
            "url": req.url,
            "method": req.method,
            "resource_type": req.resource_type,
        }) if urlparse(req.url).hostname == BASE_HOST else None)
        page.on("response", lambda res: responses_seen.append({
            "url": res.url,
            "status": res.status,
            "content_type": res.headers.get("content-type", ""),
        }) if urlparse(res.url).hostname == BASE_HOST else None)

        error = None
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:300]}"

        page_data = await page.evaluate("""() => {
          const text = (document.body?.innerText || '').trim();
          const sheets = Array.from(document.querySelectorAll('body *'))
            .filter(el => (el.children.length === 0) &&
              /match sheets|data hidden|please log in|log in/i.test(el.innerText || ''))
            .map(el => ({tag: el.tagName, text: (el.innerText || '').trim()}))
            .slice(0, 30);
          return {
            title: document.title,
            url: location.href,
            text_excerpt: text.slice(0, 12000),
            match_sheet_markers: sheets,
            images: Array.from(document.images).map(img => ({
              src: img.currentSrc || img.src,
              alt: img.alt || '',
              width: img.naturalWidth,
              height: img.naturalHeight,
            })).slice(0, 100),
            canvases: Array.from(document.querySelectorAll('canvas')).map(c => ({
              width: c.width, height: c.height,
            })),
            svgs: document.querySelectorAll('svg').length,
            iframes: Array.from(document.querySelectorAll('iframe')).map(x => x.src),
          };
        }""")
        await browser.close()

    return {
        "url_solicitada": url,
        "error_navegacion": error,
        "pagina": page_data,
        "solicitudes_mismo_dominio": requests_seen,
        "respuestas_mismo_dominio": responses_seen,
        "autenticacion": "No se intentó iniciar sesión ni reutilizar cookies.",
        "base_de_datos": "Sin conexión; este diagnóstico no modifica datos históricos.",
    }


async def main():
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python inspeccionar_hoja_partido.py URL_DEL_PARTIDO")
    report = await inspeccionar(sys.argv[1])
    Path("salida").mkdir(exist_ok=True)
    output = Path("salida/diagnostico_hoja_partido.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "archivo": str(output),
        "titulo": report["pagina"].get("title"),
        "marcadores_hoja": report["pagina"].get("match_sheet_markers"),
        "imagenes": len(report["pagina"].get("images", [])),
        "canvas": len(report["pagina"].get("canvases", [])),
        "solicitudes": len(report["solicitudes_mismo_dominio"]),
        "respuestas": len(report["respuestas_mismo_dominio"]),
        "error": report["error_navegacion"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
