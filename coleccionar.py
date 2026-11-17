import requests, json, os, time
from datetime import datetime, timedelta

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.aiscore.com/",
    "Origin": "https://www.aiscore.com"
}

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

    ya_tenemos = set(f"{p['fecha']}_{p['jugador1']}_{p['jugador2']}" for p in todos)

    dia = inicio
    while dia <= fin:
        fecha_str = dia.strftime("%Y-%m-%d")
        try:
            url = f"https://api.aiscore.com/tenis/{fecha_str}"
            r = requests.get(url, headers=HEADERS, timeout=15)
            print(f"{fecha_str}: status={r.status_code} len={len(r.text)} inicio={r.text[:120]!r}")
            if r.status_code != 200 or not r.text.strip():
                print(f"{fecha_str}: fallo, sigo - status {r.status_code} vacio")
                dia += timedelta(days=1)
                time.sleep(1)
                continue
            datos = r.json()

            nuevos = 0
            for p in datos:
                clave = f"{fecha_str}_{p.get('jugador1')}_{p.get('jugador2')}"
                if clave not in ya_tenemos:
                    todos.append({
                        "fecha": fecha_str,
                        "jugador1": p.get("jugador1"),
                        "jugador2": p.get("jugador2"),
                        "ganador": p.get("ganador"),
                        "cuota1": p.get("cuota1"),
                        "cuota2": p.get("cuota2"),
                    })
                    ya_tenemos.add(clave)
                    nuevos += 1
            print(f"{fecha_str}: +{nuevos} nuevos")
        except Exception as e:
            print(f"{fecha_str}: fallo, sigo - {e}")
        dia += timedelta(days=1)
        time.sleep(1)

    with open(archivo_salida, "w") as f:
        json.dump(todos, f)

    print(f"LISTO. Total guardado: {len(todos)} partidos, sin repetidos")

# --- TANDA 1 ---
if __name__ == "__main__":
    coleccionar_ventana("2026-03-17", "2026-11-17", "tablas.json")
