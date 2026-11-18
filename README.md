# Liga Pro Bot

Proyecto de análisis de tenis de mesa para Czech Liga Pro.

## Recolector de torneos

\`tablas_scraper.py\` consulta el listado de torneos y extrae las tablas individuales.

### Estados

El recolector reconoce etiquetas visibles en el listado: \`live\`, \`upcoming\` y \`finished\`. No asigna significados a códigos numéricos de URL sin verificarlos. Si el texto no permite identificar un único estado, lo guarda como \`unknown\` para revisión.

### Variables de entorno

- \`DIA\`: día calendario de Colombia, formato \`YYYY-MM-DD\`; por defecto hoy en \`America/Bogota\`.
- \`STATUS\`: \`all\` por defecto, o lista separada por comas: \`live,upcoming,finished\`.
- \`TORNEOS\`: IDs o URLs separados por comas; si se define, omite el descubrimiento del listado.
- \`MAX_TORNEOS\`: máximo de fichas a extraer (100 por defecto).
- \`MAX_PAGINAS\`: máximo de páginas de listado a recorrer (10 por defecto).

El rango diario se calcula en hora de Colombia y se convierte a las fechas correspondientes de Praga.

## Memoria histórica

\`db.py\` incorpora persistencia con PostgreSQL cuando existe \`DATABASE_URL\`; sin esa variable utiliza SQLite local (por defecto \`salida/liga_pro.db\`).

Guarda:
- Estado y datos más recientes de cada torneo.
- Snapshots de cada consulta para registrar la evolución de Upcoming.
- Jugadores y sus participaciones por grupo.
- Partidos con marcadores completos y recíprocos, evitando contar resultados dudosos.

Un torneo Upcoming sin grupos también se registra. Cuando aparecen sus participantes en consultas posteriores, se actualiza su estado actual y se conserva el snapshot anterior.

### Uso local

\`\`\`bash
python -m unittest test_analisis_jugadores.py test_db.py
python -c "from db import save_scrape_file; print(save_scrape_file())"
\`\`\`

Para PostgreSQL, configura \`DATABASE_URL\` con la cadena interna de conexión de Render. No guardes credenciales en el repositorio. La base de datos todavía no se crea automáticamente ni se conecta al servicio de producción.

## Salidas del recolector

- \`salida/tablas.json\`: torneos, estado detectado, grupos completos y resumen.
- \`salida/tablas.csv\`: jugadores con torneo, estado y grupo.

La tabla estadística no equivale por sí sola a una lista confirmada de próximos enfrentamientos. No se deben tratar los dos primeros jugadores de una tabla como un partido programado.

## Despliegue

El servicio de Render existente arranca \`bot_telegram.py\`. El recolector y la memoria histórica aún no están conectados a comandos ni alertas de Telegram. La integración se hará después de validar los estados y la estructura real de los datos.
