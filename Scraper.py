import asyncio
import csv
import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright

COL = ZoneInfo('America/Bogota')
PRAGA = ZoneInfo('Europe/Prague')
BASE = 'https://tt.league-pro.com/en/tournaments'
SALIDA = 'salida'
MAX_TORNEOS = 30

# Lee las filas de la tabla del grupo (mismo selector de tu código en Colab)
JS_FILAS = '''
() => Array.from(document.querySelectorAll('.c-tournament-group-item')).map(fila =>
    Array.from(fila.querySelectorAll(':scope > div')).map(celda => {
        const a = celda.querySelector('a');
        return (a ? a.innerText : celda.innerText).trim();
    })
)
'''


def url_lista(dia_col, status):
    # Un día de Colombia cubre dos fechas en Praga; zoneinfo ajusta el horario solo
    y, m, d = (int(x) for x in dia_col.split('-'))
    ini = datetime(y, m, d, 0, 0, tzinfo=COL).astimezone(PRAGA).date()
    fin = datetime(y, m, d, 23, 59, tzinfo=COL).astimezone(PRAGA).date()
    url = f'{BASE}?date_from={ini}&date_to={fin}'
    if status:
        url += f'&status={status}'
    return url


def armar_grupos(filas):
    # Cada fila: Pos, Player, Rating, n resultados, Sets, Balls, Points, Place
    # n se calcula por fila (grupos de 4 o de 5 jugadores), sin depender
    # de si el total de filas es par o impar
    grupos, actual, tam = [], [], 0
    for c in filas:
        n = len(c) - 7
        if n < 2:
            continue
        if not actual:
            tam = n
        actual.append({
            'pos': c[0], 'jugador': c[1], 'rating': c[2],
            'resultados': c[3:3 + n],
            'sets': c[3 + n], 'balls': c[4 + n],
            'points': c[5 + n], 'place': c[6 + n],
        })
        if len(actual) == tam:
            grupos.append(actual)
            actual = []
    if actual:
        grupos.append(actual)
    return grupos


async def descubrir(page, url):
    await page.goto(url, wait_until='networkidle')
    await page.wait_for_timeout(2000)
    html = await page.content()
    return sorted(set(re.findall(r'/en/tournaments/([0-9]+)', html)))


async def extraer(page, tid):
    url = f'{BASE}/{tid}'
    await page.goto(url, wait_until='networkidle')
    try:
        await page.wait_for_selector('.c-tournament-group-item', timeout=15000)
    except Exception:
        return {'url': url, 'grupos': [], 'aviso': 'tabla no encontrada'}
    filas = await page.evaluate(JS_FILAS)
    return {'url': url, 'grupos': armar_grupos(filas)}


async def main():
    torneos = [t.strip().rstrip('/').split('/')[-1]
               for t in os.environ.get('TORNEOS', '').split(',') if t.strip()]
    dia = os.environ.get('DIA') or datetime.now(COL).strftime('%Y-%m-%d')
    status = os.environ.get('STATUS', '').strip()

    resultado = {'generado': datetime.now(COL).isoformat(timespec='seconds'),
                 'dia_colombia': dia, 'torneos': {}}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
        page = await browser.new_page()

        if not torneos:
            torneos = await descubrir(page, url_lista(dia, status))
            print(f'Torneos encontrados: {len(torneos)}')

        for tid in torneos[:MAX_TORNEOS]:
            try:
                resultado['torneos'][tid] = await extraer(page, tid)
            except Exception as e:
                resultado['torneos'][tid] = {'error': type(e).__name__}
        await browser.close()

    os.makedirs(SALIDA, exist_ok=True)
    with open(f'{SALIDA}/tablas.json', 'w', encoding='utf-8') as f:
        json.dump(resultado, f, ensure_ascii=False, indent=1)

    with open(f'{SALIDA}/tablas.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['torneo', 'grupo', 'pos', 'jugador', 'rating',
                    'resultados', 'sets', 'balls', 'points', 'place'])
        for tid, t in resultado['torneos'].items():
            for i, g in enumerate(t.get('grupos', []), start=1):
                for j in g:
                    w.writerow([tid, i, j['pos'], j['jugador'], j['rating'],
                                '|'.join(j['resultados']), j['sets'],
                                j['balls'], j['points'], j['place']])
    print('Listo:', len(resultado['torneos']), 'torneos')


if __name__ == '__main__':
    asyncio.run(main())
