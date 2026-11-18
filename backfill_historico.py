"""Backfill idempotente del archivo oficial de Czech Liga Pro.

Recorre fechas históricas una por una para respetar los filtros públicos del sitio.
Puede reanudarse: cada torneo se vuelve a guardar con una marca temporal estable.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright

from db import HistoryDB
from inteligencia_torneo import integrar_inteligencia_en_resultado
from tablas_scraper import BASE, MAX_PAGINAS, SALIDA, extraer

PRAGA = ZoneInfo("Europe/Prague")
COL = ZoneInfo("America/Bogota")


def restar_meses(dia: date, meses: int) -> date:
    """Resta meses calendario conservando el día cuando existe."""
    import calendar
    indice = dia.year * 12 + dia.month - 1 - meses
    year, month0 = divmod(indice, 12)
    month = month0 + 1
    return date(year, month, min(dia.day, calendar.monthrange(year, month)[1]))


def fecha_env(nombre: str, defecto: date) -> date:
    raw = os.getenv(nombre, "").strip()
    return date.fromisoformat(raw) if raw else defecto


def url_lista_rango(inicio: date, fin: date) -> str:
    return f"{BASE}?date_from={inicio.isoformat()}&date_to={fin.isoformat()}"


async def descubrir_fecha(page, dia: date) -> list[dict]:
    """Enumera IDs de torneo en todas las páginas observadas para ese día."""
    pendientes = [url_lista_rango(dia, dia)]
    visitadas, encontrados = set(), {}
    while pendientes and len(visitadas) < MAX_PAGINAS:
        url = pendientes.pop(0)
        if url in visitadas:
            continue
        visitadas.add(url)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(700)
        items = await page.evaluate("""() => Array.from(
          document.querySelectorAll('a[href*="/en/tournaments/"]')
        ).map(a => {
          const card = a.closest(".c-tournament-item") || a.closest(".c-live-matches-item") || a;
          return {href:a.href, text:(card.innerText || card.textContent || "").trim(),
                  className:typeof card.className === "string" ? card.className : ""};
        })""")
        for item in items:
            import re
            match = re.search(r"/en/tournaments/(\\d+)", item.get("href", ""))
            if not match:
                continue
            tid = match.group(1)
            encontrados[tid] = {
                "id": tid, "estado": "finished",
                "url": f"{BASE}/{tid}",
                "texto_listado": item.get("text", "")[:500],
                "clase_tarjeta": item.get("className", ""),
            }
        links = await page.eval_on_selector_all(
            'a[href*="page="]', "(els) => els.map(a => a.href)"
        )
        for link in links:
            if link not in visitadas and link not in pendientes:
                pendientes.append(link)
    return list(encontrados.values())


async def ejecutar(inicio: date, fin: date, max_torneos: int, pausa: float) -> dict:
    db = HistoryDB()
    resultado = {
        "generado": datetime.now(COL).isoformat(timespec="seconds"),
        "rango_solicitado": {"desde": inicio.isoformat(), "hasta": fin.isoformat()},
        "torneos": {}, "resumen": {
            "dias_consultados": 0, "torneos_encontrados": 0,
            "torneos_guardados": 0, "torneos_con_error": 0,
            "torneos_sin_fecha_oficial": 0, "grupos_completos": 0,
            "partidos_reconstruidos": 0, "partidos_esperados": 0,
        },
    }
    ids_vistos = set()
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        page = await browser.new_page()
        dia = inicio
        while dia <= fin and len(ids_vistos) < max_torneos:
            resultado["resumen"]["dias_consultados"] += 1
            try:
                torneos = await descubrir_fecha(page, dia)
            except Exception as exc:
                resultado.setdefault("errores_listado", []).append({
                    "fecha": dia.isoformat(), "error": f"{type(exc).__name__}: {str(exc)[:200]}"
                })
                dia += timedelta(days=1)
                continue
            for torneo in torneos:
                tid = torneo["id"]
                if tid in ids_vistos or len(ids_vistos) >= max_torneos:
                    continue
                ids_vistos.add(tid)
                resultado["resumen"]["torneos_encontrados"] += 1
                try:
                    dato = await extraer(page, torneo)
                    dato["estado"] = "finished"
                    dato["origen_historico"] = "archivo público oficial; ficha del torneo"
                    dato["fecha_consulta_archivo"] = dia.isoformat()
                    resultado["torneos"][tid] = dato
                    if not dato.get("fecha_torneo"):
                        resultado["resumen"]["torneos_sin_fecha_oficial"] += 1
                        continue
                    counts = db.save_historical_scrape(dato)
                    resultado["resumen"]["torneos_guardados"] += 1
                    resultado["resumen"]["grupos_completos"] += dato.get("grupos_completos", 0)
                    for analisis in dato.get("analisis_cronologico", []):
                        reconstruccion = analisis.get("reconstruccion") or {}
                        resultado["resumen"]["partidos_reconstruidos"] += reconstruccion.get("partidos_reconstruidos", 0)
                        resultado["resumen"]["partidos_esperados"] += reconstruccion.get("partidos_esperados", 0)
                    dato["persistencia"] = counts
                except Exception as exc:
                    resultado["resumen"]["torneos_con_error"] += 1
                    resultado["torneos"][tid] = {
                        **torneo, "error": f"{type(exc).__name__}: {str(exc)[:250]}"
                    }
                if pausa:
                    await asyncio.sleep(pausa)
            dia += timedelta(days=1)
        await browser.close()

    integrar_inteligencia_en_resultado(resultado)
    Path(SALIDA).mkdir(parents=True, exist_ok=True)
    Path(SALIDA, "backfill_historico.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return resultado


async def main():
    hoy_praga = datetime.now(PRAGA).date()
    inicio = fecha_env("HISTORICAL_FROM", restar_meses(hoy_praga, 12))
    fin = fecha_env("HISTORICAL_TO", hoy_praga - timedelta(days=1))
    if fin < inicio:
        raise SystemExit("HISTORICAL_TO debe ser igual o posterior a HISTORICAL_FROM")
    max_torneos = int(os.getenv("MAX_HISTORICAL_TOURNAMENTS", "500"))
    pausa = float(os.getenv("HISTORICAL_PAUSE_SECONDS", "0.25"))
    resultado = await ejecutar(inicio, fin, max_torneos, pausa)
    print(json.dumps(resultado["resumen"], ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
