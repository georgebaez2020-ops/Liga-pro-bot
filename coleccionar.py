import requests, json, os
from datetime import datetime, timedelta

def coleccionar_ventana(fecha_inicio_str, fecha_fin_str, archivo_salida):
    """
    Colecciona solo entre 2 fechas, no los ultimos 240.
    Ejemplo: coleccionar_ventana("2025-11-18", "2026-03-16", "tablas_tanda2.json")
    """
    inicio = datetime.strptime(fecha_inicio_str, "%Y-%m-%d")
    fin = datetime.strptime(fecha_fin_str, "%Y-%m-%d")
    
    todos = []
    # Si ya hay datos viejos, los cargamos para no borrarlos
    if os.path.exists("tablas.json"):
        with open("tablas.json") as f:
            todos = json.load(f)
    
    # Para no repetir partidos, hacemos una lista de los que ya tenemos
    ya_tenemos = set(f"{p['fecha']}_{p['jugador1']}_{p['jugador2']}" for p in todos)
    
    dia = inicio
    while dia <= fin:
        fecha_str = dia.strftime("%Y-%m-%d")
        try:
            url = f"https://api.aiscore.com/tenis/{fecha_str}"
            r = requests.get(url, timeout=10)
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
            print(f"{fecha_str}: {nuevos} nuevos")
        except Exception as e:
            print(f"{fecha_str}: fallo, sigo - {e}")
        dia += timedelta(days=1)
    
    with open("tablas.json", "w") as f:
        json.dump(todos, f)
    
    print(f"LISTO. Total guardado: {len(todos)} partidos, sin repetidos")

# --- AQUI ELIGES QUE TANDA QUIERES ---
# Tanda 1 - Ya la estamos haciendo
# coleccionar_ventana("2026-03-17", "2026-11-17", "tablas.json")

# Tanda 2 - Cuando termines la 1, descomentas esta y corres otra vez
# coleccionar_ventana("2025-11-18", "2026-03-16", "tablas.json")

# Tanda 3 - Para ir aun mas atras
# coleccionar_ventana("2025-07-20", "2025-11-17", "tablas.json")

if __name__ == "__main__":
    # Por ahora solo corre la Tanda 1
    coleccionar_ventana("2026-03-17", "2026-11-17", "tablas.json")
