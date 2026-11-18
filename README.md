# Liga Pro Bot

Proyecto de análisis de tenis de mesa para Czech Liga Pro.

## Recolector de torneos

`tablas_scraper.py` consulta el listado de torneos y extrae las tablas individuales.

### Estados

El recolector reconoce etiquetas visibles en el listado: `live`, `upcoming` y `finished`. No asigna significados a códigos numéricos de URL sin verificarlos. Si el texto no permite identificar un único estado, lo guarda como `unknown` para revisión.

### Variables de entorno

- `DIA`: día calendario de Colombia, formato `YYYY-MM-DD`; por defecto hoy en `America/Bogota`.
- `STATUS`: `all` por defecto, o lista separada por comas: `live,upcoming,finished`.
- `TORNEOS`: IDs o URLs separados por comas; si se define, omite el descubrimiento del listado.
- `MAX_TORNEOS`: máximo de fichas a extraer (100 por defecto).
- `MAX_PAGINAS`: máximo de páginas de listado a recorrer (10 por defecto).

Ejemplo:

```bash
DIA=2026-11-17 STATUS=live,upcoming python tablas_scraper.py
```

El rango diario se calcula en hora de Colombia y se convierte a las fechas correspondientes de Praga.

### Salidas

- `salida/tablas.json`: torneos, estado detectado, grupos completos y resumen.
- `salida/tablas.csv`: jugadores con torneo, estado y grupo.

La tabla estadística no equivale por sí sola a una lista confirmada de próximos enfrentamientos. No se deben tratar los dos primeros jugadores de una tabla como un partido programado.

## Despliegue

El servicio de Render existente arranca `bot_telegram.py`. El recolector aún no está conectado a comandos ni alertas de Telegram. Esa integración se hará después de validar los estados y la estructura real de los datos.
