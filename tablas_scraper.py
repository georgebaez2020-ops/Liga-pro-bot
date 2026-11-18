import asyncio
import csv
import json
import os
import re
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright

from db import HistoryDB
from inteligencia_torneo import integrar_inteligencia_en_resultado

COL = ZoneInfo("America/Bogota")
PRAGA = ZoneInfo("Europe/Prague")
BASE = "https://tt.league-pro.com/en/tournaments"
SALIDA = "salida"
MAX_TORNEOS = int(os.getenv("MAX_TORNEOS", "100"))
MAX_PAGINAS = int(os.getenv("MAX_PAGINAS", "10"))
ESTADOS = ("live", "upcoming", "finished")
ETIQUETAS_ESTADO = {
    "live": ("live", "in progress"),
    "upcoming": ("upcoming",),
    "finished": ("finished",),
}

# En la ficha de cada torneo: una fila por jugador.
JS_FILAS = r"""
() => Array.from(document.querySelectorAll('.c-tournament-group-item')).map(fila =>
    Array.from(fila.querySelectorAll(':scope > div')).map(celda => {
        const a = celda.querySelector('a');
        return (a ? a.innerText : celda.innerText).trim();
    })
)
"""

# En el listado, conserva el texto de la fila contenedora para leer el estado
# que muestra la propia web. No se asignan códigos numéricos supuestos.
JS_TORNEOS = r"""
() => Array.from(document.querySelectorAll('a[href*="/en/tournaments/"]')).map(a => {
  const card = a.closest(".c-tournament-item") || a.closest(".c-live-matches-item") || a;
  return {
    href: a.href,
    text: (card.innerText || card.textContent || "").trim(),
    className: typeof card.className === "string" ? card.className : "",
    linkClass: typeof a.className === "string" ? a.className : ""
  };
})
"""


def url_lista(dia_col):
    """Un día de Colombia convertido al rango de fechas que toca en Praga."""
    y, m, d = (int(x) for x in dia_col.split("-"))
    inicio = datetime(y, m, d, 0, 0, tzinfo=COL).astimezone(PRAGA).date()
    fin = datetime(y, m, d, 23, 59, tzinfo=COL).astimezone(PRAGA).date()
    return f"{BASE}?date_from={inicio}&date_to={fin}"


def normalizar_estado(texto, clase=""):
    """Clasifica usando la tarjeta concreta, no texto de contenedores globales."""
    clase = (clase or "").lower()
    texto = (texto or "").lower()
    if "c-live-matches-item" in clase or "c-live-matches-item" in (clase or "").lower():
        return "live"
    coincidencias = {
        estado for estado, etiquetas in ETIQUETAS_ESTADO.items()
        if any(re.search(rf"\b{re.escape(etiqueta)}\b", texto) for etiqueta in etiquetas)
    }
    return coincidencias.pop() if len(coincidencias) == 1 else "unknown"

def armar_grupos(filas):
    """
    Convierte filas de jugadores en grupos de 4 o 5.
    El número de resultados de la fila (columnas menos 7) indica el tamaño
    del grupo. Se descartan filas incompletas y nunca se mezclan grupos
    incompletos con el siguiente.
    """
    grupos = []
    actual = []
    tam_actual = None

    for c in filas:
        if len(c) < 11:
            continue
        n = len(c) - 7
        if n not in (4, 5):
            continue

        jugador = {
            "pos": c[0],
            "jugador": c[1],
            "rating": c[2],
            "resultados": c[3:3 + n],
            "sets": c[3 + n],
            "balls": c[4 + n],
            "points": c[5 + n],
            "place": c[6 + n],
        }

        # Una nueva posición 1 señala el comienzo de otro grupo.
        if actual and (n != tam_actual or str(jugador["pos"]).strip() == "1"):
            if len(actual) == tam_actual:
                grupos.append(actual)
            actual = []
            tam_actual = None

        if not actual:
            tam_actual = n
        actual.append(jugador)

        if len(actual) == tam_actual:
            grupos.append(actual)
            actual = []
            tam_actual = None

    # No se publica un grupo parcial como si estuviera completo.
    return grupos


async def descubrir(page, dia_col, estados_solicitados):
    """Recorre las páginas del listado y clasifica por la etiqueta visible."""
    primera = url_lista(dia_col)
    pendientes = [primera]
    visitadas = set()
    encontrados = {}

    while pendientes and len(visitadas) < MAX_PAGINAS:
        url = pendientes.pop(0)
        if url in visitadas:
            continue
        visitadas.add(url)

        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1200)

        filas = await page.evaluate(JS_TORNEOS)
        # Diagnóstico temporal: estructura real de tarjetas y etiquetas visibles.
        os.makedirs(SALIDA, exist_ok=True)
        with open(f"{SALIDA}/debug_listado.json", "w", encoding="utf-8") as debug_file:
            json.dump(filas, debug_file, ensure_ascii=False, indent=2)
        for item in filas:
            href = item.get("href", "")
            match = re.search(r"/en/tournaments/(\d+)", href)
            if not match:
                continue
            tid = match.group(1)
            estado = normalizar_estado(item.get("text", ""), item.get("className", ""))
            # Con filtros concretos también conservamos los "unknown" para inspección:
            # es preferible revisar un torneo que descartarlo silenciosamente.
            if estados_solicitados == {"all"} or estado in estados_solicitados or estado == "unknown":
                encontrados[tid] = {
                    "id": tid,
                    "estado": estado,
                    "url": f"{BASE}/{tid}",
                    "texto_listado": item.get("text", "")[:500],
                    "clase_tarjeta": item.get("className", ""),
                }

        # La web puede mostrar paginación numerada. Se recorren enlaces
        # de página observados, con límite para evitar bucles.
        paginas = await page.eval_on_selector_all(
            'a[href*="page="]', "(els) => els.map(a => a.href)"
        )
        for siguiente in paginas:
            if siguiente not in visitadas and siguiente not in pendientes:
                pendientes.append(siguiente)

    return list(encontrados.values())


async def extraer(page, torneo):
    tid = torneo["id"]
    url = torneo["url"]
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        await page.wait_for_selector(".c-tournament-group-item", timeout=15000)
    except Exception:
        return {**torneo, "grupos": [], "aviso": "tabla no encontrada"}

    filas = await page.evaluate(JS_FILAS)
    grupos = armar_grupos(filas)
    return {
        **torneo,
        "grupos": grupos,
        "filas_leidas": len(filas),
        "grupos_completos": len(grupos),
        "aviso": None if grupos else "no se pudieron formar grupos completos de 4 o 5",
    }


def estados_configurados():
    raw = os.getenv("STATUS", "all").strip().lower()
    if raw in ("", "all", "todos"):
        return {"all"}
    solicitados = {x.strip() for x in raw.split(",") if x.strip()}
    validos = solicitados.intersection(set(ESTADOS))
    desconocidos = solicitados - set(ESTADOS)
    if desconocidos:
        print("Estados ignorados (usa live,upcoming,finished):", ", ".join(sorted(desconocidos)))
    return validos or {"all"}


async def main():
    torneos_manual = [
        x.strip().rstrip("/").split("/")[-1]
        for x in os.getenv("TORNEOS", "").split(",") if x.strip()
    ]
    dia = os.getenv("DIA") or datetime.now(COL).strftime("%Y-%m-%d")
    estados = estados_configurados()

    resultado = {
        "generado": datetime.now(COL).isoformat(timespec="seconds"),
        "zona_horaria": "America/Bogota",
        "dia_colombia": dia,
        "filtro_estados": sorted(estados),
        "torneos": {},
        "resumen": {"live": 0, "upcoming": 0, "finished": 0, "unknown": 0},
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        page = await browser.new_page()

        if torneos_manual:
            lista = [
                {"id": tid, "estado": "unknown", "url": f"{BASE}/{tid}",
                 "texto_listado": "TORNEOS configurado manualmente"}
                for tid in torneos_manual
            ]
        else:
            lista = await descubrir(page, dia, estados)
            print(f"Torneos identificados en el listado: {len(lista)}")

        for torneo in lista[:MAX_TORNEOS]:
            tid = torneo["id"]
            try:
                dato = await extraer(page, torneo)
                resultado["torneos"][tid] = dato
                resultado["resumen"][dato["estado"]] += 1
            except Exception as exc:
                resultado["torneos"][tid] = {
                    **torneo, "grupos": [],
                    "error": f"{type(exc).__name__}: {str(exc)[:250]}",
                }
                resultado["resumen"][torneo["estado"]] += 1

        await browser.close()

    os.makedirs(SALIDA, exist_ok=True)
    with open(f"{SALIDA}/tablas.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    # Analiza cada grupo antes de guardar; el JSON y los snapshots conservan el análisis.
    integrar_inteligencia_en_resultado(resultado)
    print("Resumen de inteligencia:", json.dumps(resultado["resumen_inteligencia"], ensure_ascii=False))

    # Persistencia: PostgreSQL si DATABASE_URL existe; SQLite local para desarrollo.
    guardado = HistoryDB().save_scrape(resultado)
    print("Memoria histórica actualizada:", json.dumps(guardado, ensure_ascii=False))

    with open(f"{SALIDA}/tablas.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "torneo", "estado", "grupo", "pos", "jugador", "rating",
            "resultados", "sets", "balls", "points", "place",
        ])
        for tid, torneo in resultado["torneos"].items():
            for numero_grupo, grupo in enumerate(torneo.get("grupos", []), start=1):
                for jugador in grupo:
                    w.writerow([
                        tid, torneo.get("estado", "unknown"), numero_grupo,
                        jugador["pos"], jugador["jugador"], jugador["rating"],
                        "|".join(jugador["resultados"]), jugador["sets"],
                        jugador["balls"], jugador["points"], jugador["place"],
                    ])

    print("Proceso terminado.")
    print("Resumen por estado:", json.dumps(resultado["resumen"], ensure_ascii=False))
    print(f"Archivos generados: {SALIDA}/tablas.json y {SALIDA}/tablas.csv")


if __name__ == "__main__":
    asyncio.run(main())
