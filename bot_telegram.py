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

JS_FILAS = '''
() => Array.from(document.querySelectorAll('.c-tournament-group-item')).map(fila =>
    Array.from(fila.querySelectorAll(':scope > div')).map(celda => {
        const a = celda.querySelector('a');
        return (a ? a.innerText : celda.innerText).trim();
    })
)
'''

def url_lista(dia_col, status):
    y, m, d = (int(x) for x in dia_col.split('-'))
    ini = datetime(y, m, d, 0, 0, tzinfo=COL).astimezone(PRAGA).date()
    fin = datetime(y, m, d, 23, 59, tzinfo=COL).astimezone(PRAGA).date()
    url = f'{BASE}?date_from={ini}&date_to={fin}'
    if status:
        url += f'&status={status}'
    return url

def armar_grupos(filas):
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

# --- NUEVO: CUOTAS DESDE AISCORE ---
async def cuota_aiscore(page, jugador1, jugador2):
    q = f"{jugador1} {jugador2}"
    url = f"https://m.aiscore.com/search?keyword={q.replace(' ', '%20')}"
    try:
        await page.goto(url, wait_until='networkidle')
        await page.wait_for_timeout(2000)
        html = await page.content()
        cuotas = re.findall(r'\b(1\.\d{2}|[2-9]\.\d{2})\b', html)[:2]
        if len(cuotas) >= 2:
            return float(cuotas[0]), float(cuotas[1])
    except Exception as e:
        print(f"Sin cuota AiScore para {jugador1} vs {jugador2}: {e}")
    return None, None

def prob_por_rating(r1, r2):
    try:
        r1 = float(str(r1).replace(',', '.'))
        r2 = float(str(r2).replace(',', '.'))
    except:
        return 0.5
    return 1 / (1 + 10 ** ((r2 - r1) / 400))

async def main():
    torneos = [t.strip().rstrip('/').split('/')[-1]
               for t in os.environ.get('TORNEOS', '').split(',') if t.strip()]
    dia = os.environ.get('DIA') or datetime.now(COL).strftime('%Y-%m-%d')
    status = os.environ.get('STATUS', '').strip()

    resultado = {'generado': datetime.now(COL).isoformat(timespec='seconds'),
                 'dia_colombia': dia, 'torneos': {}}
    recomendados = []

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

        # --- NUEVO: ANALIZAR SOLO LOS MEJORES ---
        for tid, t in resultado['torneos'].items():
            for grupo in t.get('grupos', []):
                if len(grupo) >= 2:
                    j1 = grupo[0]
                    j2 = grupo[1]
                    c1, c2 = await cuota_aiscore(page, j1['jugador'], j2['jugador'])
                    if not c1 or not c2:
                        continue
                    # Quien tiene mas rating es el favorito
                    try:
                        r1 = float(str(j1['rating']).replace(',', '.'))
                        r2 = float(str(j2['rating']).replace(',', '.'))
                    except:
                        continue
                    if r1 >= r2:
                        fav, fav_r, otro_r, cuota_fav = j1['jugador'], r1, r2, c1
                    else:
                        fav, fav_r, otro_r, cuota_fav = j2['jugador'], r2, r1, c2
                    p_modelo = prob_por_rating(fav_r, otro_r)
                    p_cuota = 1 / cuota_fav if cuota_fav else 0
                    valor = p_modelo - p_cuota
                    # FILTRO QUE PEDISTE: 70% o mas + valor 5% o mas
                    if p_modelo >= 0.70 and valor >= 0.05:
                        recomendados.append({
                            'partido': f"{j1['jugador']} vs {j2['jugador']}",
                            'favorito': fav,
                            'prob_modelo': round(p_modelo*100, 1),
                            'prob_cuota': round(p_cuota*100, 1),
                            'cuota': cuota_fav,
                            'valor': round(valor*100, 1),
                            'torneo': tid
                        })
        await browser.close()

    # Ordenar de mayor a menor probabilidad
    recomendados = sorted(recomendados, key=lambda x: x['prob_modelo'], reverse=True)[:5]

    os.makedirs(SALIDA, exist_ok=True)
    with open(f'{SALIDA}/tablas.json', 'w', encoding='utf-8') as f:
        json.dump(resultado, f, ensure_ascii=False, indent=1)
    with open(f'{SALIDA}/pronosticos.json', 'w', encoding='utf-8') as f:
        json.dump({'generado': resultado['generado'], 'recomendados': recomendados}, f, ensure_ascii=False, indent=1)

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
    print('Listo:', len(resultado['torneos']), 'torneos, Recomendados:', len(recomendados))

if __name__ == '__main__':
    asyncio.run(main())
