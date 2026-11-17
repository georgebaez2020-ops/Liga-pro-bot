import json, os, requests, time
from datetime import datetime, timedelta

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

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    dia = inicio
    while dia <= fin:
        fecha_str = dia.strftime("%Y-%m-%d")
        try:
            # API publica de SofaScore para tenis de mesa
            url = f"https://www.sofascore.com/api/v1/sport/table-tennis/scheduled-events/{fecha_str}"
            print(f"Abriendo {fecha_str} -> {url}")
            r = requests.get(url, headers=headers, timeout=30)
            print(f"{fecha_str}: status={r.status_code} len={len(r.text)}")

            if r.status_code == 200:
                data = r.json()
                eventos = data.get("events", [])
                print(f"{fecha_str}: encontrados {len(eventos)}")
                for ev in eventos:
                    home = ev.get("homeTeam", {}).get("name", "?")
                    away = ev.get("awayTeam", {}).get("name", "?")
                    hs = ev.get("homeScore", {})
                    aws = ev.get("awayScore", {})
                    torneo = ev.get("tournament", {}).get("name", "")
                    todos.append({
                        "fecha": fecha_str,
                        "jugador1": home,
                        "jugador2": away,
                        "marcador": f"{hs.get('current', '')}-{aws.get('current', '')}",
                        "torneo": torneo,
                        "deporte": "table-tennis",
                        "id": ev.get("id")
                    })
            else:
                print(f"{fecha_str}: no dejo, muestro inicio: {r.text[:500]}")

        except Exception as e:
            print(f"{fecha_str}: fallo - {e}")

        dia += timedelta(days=1)
        time.sleep(2)

    os.makedirs("data", exist_ok=True)
    with open(archivo_salida, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)
    with open("data/tablas.json", "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)

    print(f"LISTO. Total guardado: {len(todos)}")

if __name__ == "__main__":
    # 1 DIA DE PRUEBA
    coleccionar_ventana("2026-03-17", "2026-03-17", "tablas.json")
