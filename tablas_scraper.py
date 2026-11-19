import asyncio
import csv
import gc
import json
import os
import re
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright

from db import HistoryDB
from reconstruccion_torneo import (
    _nombre_ficha_coincide, consolidar_partidos_torneo, parsear_detalle_oficial,
    parsear_marcador_sets_live, reconstruir_secuencia,
)

COL = ZoneInfo("America/Bogota")
PRAGA = ZoneInfo("Europe/Prague")
BASE = "https://tt.league-pro.com/en/tournaments"
SALIDA = "salida"
MAX_TORNEOS = int(os.getenv("MAX_TORNEOS", "100"))
MAX_PAGINAS = int(os.getenv("MAX_PAGINAS", "10"))
ESTADOS = ("live", "upcoming", "finished")
ETIQUETAS_ESTADO = {
    "live": ("live", "in progress", "en vivo", "en directo"),
    "upcoming": ("upcoming", "próximamente", "proximamente", "planificado", "planificada"),
    "finished": ("finished", "finalizado", "finalizada"),
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
() => Array.from(document.querySelectorAll('a[href*="/en/tournaments/"]'))
  // Solo enlaces a la ficha del torneo. Los enlaces de partidos tienen
  // segmentos adicionales (/ID_PARTIDO) y no deben convertirse en torneos.
  .filter(a => /^\/en\/tournaments\/\d+\/?$/.test(new URL(a.href).pathname))
  .map(a => {
    // La página publica los torneos en filas con columnas Date, Tournament,
    // Players, Status y Winner. Leer la fila completa permite obtener el
    // estado oficial; usar solo el <a> deja el estado como unknown.
    const card = a.closest("tr")
      || a.closest(".c-tournament-item")
      || a.closest(".c-live-matches-item")
      || a.parentElement;
    return {
      href: a.href,
      text: (card?.innerText || card?.textContent || "").trim(),
      className: typeof card?.className === "string" ? card.className : "",
      linkClass: typeof a.className === "string" ? a.className : ""
    };
  })
"""

JS_ENLACES_PARTIDOS = r"""
(tid) => Array.from(document.querySelectorAll('a[href*="/en/tournaments/"]'))
  .map(a => a.href)
  .filter(href => {
    const parts = new URL(href).pathname.split('/').filter(Boolean);
    return parts.length >= 4 && parts[0] === 'en' &&
      parts[1] === 'tournaments' && parts[2] === String(tid) &&
      /^\d+$/.test(parts[3]);
  })
  .filter((href, index, all) => all.indexOf(href) === index)
"""


def _marcador_en_ficha_partido(texto, jugador_a, jugador_b):
    """Lee el marcador de sets entre los dos jugadores, sin confundir puntos del set."""
    lineas = [line.strip() for line in str(texto or "").splitlines() if line.strip()]
    def es_jugador(linea, nombre):
        # Las fichas oficiales pueden anteponer o añadir el rating (#847 / (847)).
        nombre_limpio = re.sub(r"#\s*\d+\b|\(\s*\d+\s*\)", " ", linea)
        return _nombre_ficha_coincide(nombre_limpio, str(nombre or ""))

    pos_a = [i for i, line in enumerate(lineas) if es_jugador(line, jugador_a)]
    pos_b = [i for i, line in enumerate(lineas) if es_jugador(line, jugador_b)]
    if len(pos_a) != 1 or len(pos_b) != 1 or pos_a[0] == pos_b[0]:
        return None
    a, b = pos_a[0], pos_b[0]
    lo, hi = sorted((a, b))
    scores = [parsear_marcador_sets_live(line) for line in lineas[lo + 1:hi]]
    scores = [score for score in scores if score is not None]
    if len(scores) != 1:
        return None
    score = scores[0]
    if a < b:
        return score
    left, right = score.split(":")
    return f"{right}:{left}"


async def enriquecer_marcadores_live(page, torneo_id, partidos):
    """Consulta fichas individuales oficiales y añade solo parciales no ambiguos."""
    live = [m for m in partidos if m.get("estado") == "live" and not m.get("marcador_live_sets")]
    if not live:
        return {"consultados": 0, "actualizados": 0}
    enlaces = await page.evaluate(JS_ENLACES_PARTIDOS, str(torneo_id))
    consultados = actualizados = 0
    for href in enlaces:
        try:
            await page.goto(href, wait_until="domcontentloaded", timeout=30000)
            texto = await page.locator("body").inner_text()
            consultados += 1
        except Exception:
            continue
        for partido in live:
            if partido.get("marcador_live_sets"):
                continue
            score = _marcador_en_ficha_partido(
                texto, partido.get("jugador_a"), partido.get("jugador_b")
            )
            if score is not None:
                partido["marcador_live_sets"] = score
                partido["fuente_marcador_live"] = href
                actualizados += 1
                break
    return {"consultados": consultados, "actualizados": actualizados}


def url_lista(dia_col):
    """Un día de Colombia convertido al rango de fechas que toca en Praga."""
    y, m, d = (int(x) for x in dia_col.split("-"))
    inicio = datetime(y, m, d, 0, 0, tzinfo=COL).astimezone(PRAGA).date()
    fin = datetime(y, m, d, 23, 59, tzinfo=COL).astimezone(PRAGA).date()
    return f"{BASE}?date_from={inicio}&date_to={fin}"


def rango_fechas_praga(dia_col):
    """Devuelve las fechas de Praga que cubren el día calendario de Colombia."""
    y, m, d = (int(x) for x in dia_col.split("-"))
    inicio = datetime(y, m, d, 0, 0, tzinfo=COL).astimezone(PRAGA).date()
    fin = datetime(y, m, d, 23, 59, tzinfo=COL).astimezone(PRAGA).date()
    return inicio.isoformat(), fin.isoformat()


def _aplicar_filtro_fecha(url, fecha_desde, fecha_hasta):
    """Conserva la paginación, pero fuerza siempre el rango del día solicitado."""
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    query["date_from"] = [fecha_desde]
    query["date_to"] = [fecha_hasta]
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(query, doseq=True), parts.fragment))


def normalizar_estado(texto, clase=""):
    """Clasifica usando la tarjeta concreta, no texto de contenedores globales."""
    clase = (clase or "").lower()
    texto = (texto or "").lower()
    if "c-live-matches-item" in clase or "c-live-matches-item" in (clase or "").lower():
        return "live"
    coincidencias = {
        estado for estado, etiquetas in ETIQUETAS_ESTADO.items()
        if any(etiqueta in texto for etiqueta in etiquetas)
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
    fecha_desde, fecha_hasta = rango_fechas_praga(dia_col)
    primera = url_lista(dia_col)
    pendientes = [primera]
    visitadas = set()
    encontrados = {}
    filas_diagnostico = []

    while pendientes and len(visitadas) < MAX_PAGINAS:
        url = _aplicar_filtro_fecha(pendientes.pop(0), fecha_desde, fecha_hasta)
        if url in visitadas:
            continue
        visitadas.add(url)

        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1200)

        filas = await page.evaluate(JS_TORNEOS)
        # Acumulamos el diagnóstico de todas las páginas; no sobrescribir la anterior.
        filas_diagnostico.extend(filas)
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
            siguiente = _aplicar_filtro_fecha(siguiente, fecha_desde, fecha_hasta)
            if siguiente not in visitadas and siguiente not in pendientes:
                pendientes.append(siguiente)

    os.makedirs(SALIDA, exist_ok=True)
    with open(f"{SALIDA}/debug_listado.json", "w", encoding="utf-8") as debug_file:
        json.dump(filas_diagnostico, debug_file, ensure_ascii=False, indent=2)
    return list(encontrados.values())


async def extraer(page, torneo):
    tid = torneo["id"]
    url = torneo["url"]
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    # La ficha puede tener calendario de partidos aunque todavía no publique
    # grupos. Nunca salir antes de leer el contenido visible.
    try:
        await page.wait_for_selector(".c-tournament-group-item", timeout=15000)
    except Exception:
        pass

    filas = await page.evaluate(JS_FILAS)
    grupos = armar_grupos(filas)
    # "Players" y "Tournament games" también existen en torneos Upcoming.
    detalle_texto = await page.locator("body").inner_text()
    analisis_cronologico = []
    partidos_ficha_sin_grupo = []
    if not grupos:
        extraido = parsear_detalle_oficial(detalle_texto, [])
        partidos_ficha_sin_grupo = extraido["partidos"]
    for numero, grupo in enumerate(grupos, start=1):
        extraido = parsear_detalle_oficial(detalle_texto, grupo)
        partidos_grupo = [
            partido for partido in extraido["partidos"]
            if partido.get("estado") == "finished" and partido.get("fase") == "group"
        ]
        reconstruido = reconstruir_secuencia(
            [p.get("jugador", "") for p in grupo],
            partidos_grupo,
            extraido.get("rating_por_jugador", {}),
        )
        analisis_cronologico.append({
            "grupo": numero,
            "fecha_torneo": extraido.get("fecha_torneo"),
            "partidos_ficha": extraido["partidos"],
            "rating_por_jugador": extraido["rating_por_jugador"],
            "reconstruccion": reconstruido,
            "advertencias_extraccion": extraido["advertencias"],
        })
    partidos_para_enriquecer = list(partidos_ficha_sin_grupo)
    for analisis in analisis_cronologico:
        partidos_para_enriquecer.extend(analisis.get("partidos_ficha", []))
    await enriquecer_marcadores_live(page, tid, partidos_para_enriquecer)
    calendario = consolidar_partidos_torneo(analisis_cronologico, partidos_ficha_sin_grupo)
    # La fecha se toma de la ficha oficial; las horas de Tournament games
    # corresponden a la hora local de la competición (Praga).
    fecha_torneo = next(
        (x.get("fecha_torneo") for x in analisis_cronologico if x.get("fecha_torneo")),
        None,
    )
    if not fecha_torneo:
        fecha_torneo = extraido.get("fecha_torneo")
    for partido in calendario["partidos"]:
        partido["fecha"] = fecha_torneo
        partido["zona_horaria"] = "Europe/Prague" if fecha_torneo else None
        hora = partido.get("hora")
        if fecha_torneo and isinstance(hora, str) and re.fullmatch(r"\d{1,2}:\d{2}", hora):
            try:
                local = datetime.fromisoformat(f"{fecha_torneo}T{hora}").replace(tzinfo=PRAGA)
                partido["scheduled_at"] = local.isoformat(timespec="minutes")
                partido["hora_praga"] = local.strftime("%H:%M")
                partido["hora_colombia"] = local.astimezone(COL).strftime("%H:%M")
                partido["fecha_colombia"] = local.astimezone(COL).date().isoformat()
            except ValueError:
                partido["scheduled_at"] = None
        else:
            partido["scheduled_at"] = None
    return {
        **torneo,
        "fecha_torneo": fecha_torneo,
        "zona_horaria": "Europe/Prague" if fecha_torneo else None,
        **calendario,
        "grupos": grupos,
        "detalle_texto": detalle_texto,
        "analisis_cronologico": analisis_cronologico,
        "partidos_ficha": partidos_ficha_sin_grupo,
        "filas_leidas": len(filas),
        "grupos_completos": len(grupos),
        "aviso": None if grupos else "no se pudieron formar grupos completos de 4 o 5",
    }


def clasificar_estado_partidos(partidos, estado_listado="unknown"):
    """
    Interpreta el estado operativo desde los partidos de la ficha oficial.

    La etiqueta del listado solo sirve para descubrir el torneo: nunca puede
    convertir por sí sola un torneo en LIVE. Para declarar LIVE debe existir
    al menos un partido cuyo marcador/estado oficial sea LIVE.
    """
    estados = {
        str(partido.get("estado") or "").strip().casefold()
        for partido in (partidos or [])
        if partido.get("estado")
    }
    if "live" in estados:
        return "live"
    if estados.intersection({"planned", "upcoming"}):
        return "upcoming"
    if estados and estados.issubset({"finished"}):
        return "finished"

    # Si la ficha no permitió leer estados de partidos, no inventar uno
    # heredándolo de una etiqueta posiblemente vieja del listado.
    return "unknown"


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
        # Reduce el consumo de RAM en Render: el scraper solo necesita HTML/texto
        # y las respuestas de red; no necesita descargar imágenes, fuentes ni video.
        async def bloquear_recursos_pesados(route):
            if route.request.resource_type in {"image", "media", "font"}:
                await route.abort()
            else:
                await route.continue_()
        await page.route("**/*", bloquear_recursos_pesados)

        if torneos_manual:
            lista = [
                {"id": tid, "estado": "unknown", "url": f"{BASE}/{tid}",
                 "texto_listado": "TORNEOS configurado manualmente"}
                for tid in torneos_manual
            ]
        else:
            lista = await descubrir(page, dia, estados)
            print(f"Torneos identificados en el listado: {len(lista)}")

        # Procesar primero torneos activos o próximos para que el límite de
        # memoria no deje fuera los eventos de mayor interés operativo.
        prioridad_estado = {"live": 0, "upcoming": 1, "unknown": 2, "finished": 3}
        lista = sorted(
            enumerate(lista),
            key=lambda par: (prioridad_estado.get(str(par[1].get("estado", "unknown")).lower(), 2), par[0]),
        )
        lista = [torneo for _, torneo in lista]
        if len(lista) > MAX_TORNEOS:
            omitidos = lista[MAX_TORNEOS:]
            print(
                f"Se procesarán {MAX_TORNEOS} de {len(lista)} torneos; "
                f"quedan pendientes: " + ", ".join(
                    f'{x.get("id")}({x.get("estado", "unknown")})' for x in omitidos
                )
            )
        for torneo in lista[:MAX_TORNEOS]:
            tid = torneo["id"]
            try:
                dato = await extraer(page, torneo)
                # Reconciliamos la etiqueta del listado con el calendario extraído.
                # Un estado LIVE obsoleto no debe prevalecer si todos los partidos
                # que publica la ficha ya terminaron. Si aún hay partidos LIVE o
                # pendientes, el torneo conserva ese estado operativo.
                estado_oficial = str(torneo.get("estado") or "unknown").casefold()
                estado_calendario = clasificar_estado_partidos(
                    dato.get("partidos", []), estado_oficial
                )
                dato["estado"] = estado_calendario
                if estado_calendario != estado_oficial:
                    print(
                        f"Torneo {tid}: estado del listado={estado_oficial}; "
                        f"estado según partidos={estado_calendario}. Se guarda {estado_calendario}."
                    )
                fecha_oficial = dato.get("fecha_torneo")
                fecha_desde, fecha_hasta = rango_fechas_praga(dia)
                fechas_partidos_col = {
                    str(p.get("fecha_colombia"))
                    for p in dato.get("partidos", [])
                    if p.get("fecha_colombia")
                }
                # Si la ficha publica horas, decide por el día real del partido
                # en Colombia, no por la fecha civil de Praga.
                # Un torneo pertenece al día consultado si coincide su fecha
                # oficial de Praga dentro del rango que cubre el día colombiano,
                # O si alguno de sus partidos cae en el día colombiano solicitado.
                # No descartamos el torneo solo porque la conversión horaria mueva
                # un partido a la víspera en Colombia.
                corresponde_hoy = (
                    dia in fechas_partidos_col
                    or bool(fecha_oficial and fecha_desde <= fecha_oficial <= fecha_hasta)
                )
                if not corresponde_hoy:
                    print(
                        f"Torneo {tid} descartado: fecha oficial {fecha_oficial or 'no publicada'}; "
                        f"fechas de partidos en Colombia {sorted(fechas_partidos_col)}; "
                        f"día solicitado {dia}."
                    )
                    continue
                resultado["torneos"][tid] = dato
                resultado["resumen"][dato["estado"]] += 1
            except Exception as exc:
                resultado["torneos"][tid] = {
                    **torneo, "grupos": [],
                    "error": f"{type(exc).__name__}: {str(exc)[:250]}",
                }
                resultado["resumen"][torneo["estado"]] += 1

        await browser.close()
        del page
        del browser
        gc.collect()

    os.makedirs(SALIDA, exist_ok=True)
    with open(f"{SALIDA}/tablas.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    # Persistencia: PostgreSQL si DATABASE_URL existe; SQLite local para desarrollo.
    history_db = HistoryDB()
    guardado = history_db.save_scrape(resultado)
    print("Memoria histórica actualizada:", json.dumps(guardado, ensure_ascii=False))

    # En esta fase solo se conserva el historial scrapeado; el análisis avanzado queda aplazado.
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
