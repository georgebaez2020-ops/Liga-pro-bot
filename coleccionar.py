import requests, json, os
from datetime import datetime, timedelta

# --- CONFIG ---
# Vamos a coleccionar desde hace 8 meses hasta hoy
DIAS_ATRAS = 240  # 8 meses

def coleccionar_historicos():
    todos = []
    hoy = datetime.now()
    
    print("Empezando a coleccionar...")
    
    for i in range(DIAS_ATRAS, 0, -1):
        fecha = hoy - timedelta(days=i)
        fecha_str = fecha.strftime("%Y-%m-%d")
        
        # Aqui conectamos con AiScore
        # Intentamos traer partidos + cuotas + resultado
        try:
            # 1. Partidos de ese dia
            url = f"https://api.aiscore.com/tenis/{fecha_str}"
            # NOTA: Si AiScore te bloquea, lo cambiamos a otra fuente
            r = requests.get(url, timeout=10)
            datos = r.json()
            
            for p in datos:
                registro = {
                    "fecha": fecha_str,
                    "jugador1": p.get("jugador1"),
                    "jugador2": p.get("jugador2"),
                    "ganador": p.get("ganador"), # Quien gano de verdad
                    "cuota1": p.get("cuota1"),   # Cuota que habia ese dia
                    "cuota2": p.get("cuota2"),
                    "prob_predicha": None, # La llenamos despues
                    "acertado": None
                }
                todos.append(registro)
            print(f"{fecha_str}: {len(datos)} partidos coleccionados")
            
        except Exception as e:
            print(f"{fecha_str}: No pude, sigo con el siguiente - {e}")
            continue
    
    # Guardar todo
    with open("tablas.json", "w") as f:
        json.dump(todos, f)
    
    print(f"LISTO. Coleccionados {len(todos)} partidos en total")
    return todos

if __name__ == "__main__":
    coleccionar_historicos()
