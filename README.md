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


## Inteligencia del torneo

`inteligencia_torneo.py` calcula una clasificación de grupo provisional a partir de los marcadores completos y recíprocos:

- 2 puntos por victoria y 1 por derrota.
- Desempates en el orden del reglamento: sets ganados, diferencia de sets, diferencia de puntos, puntos anotados y enfrentamiento directo únicamente al comparar exactamente dos jugadores.
- Partidos pendientes y marcadores inconsistentes se muestran por separado.
- Objetivos reglamentarios: en grupos de 4, puestos 1-2 disputan la final y 3-4 el partido por el tercer puesto; en grupos de 5, el quinto queda eliminado de la fase final y los otros cuatro disputan partidos de posición.
- Escenarios: enumera todas las combinaciones de victoria/derrota de los duelos pendientes y calcula rangos de puestos por puntos para cada jugador. Expone si puede alcanzar el top 2 o la fase final y si lo asegura por puntos. Los empates se expresan como rangos porque los desempates futuros dependen de sets/puntos aún desconocidos; marcadores inconsistentes se excluyen y marcan los escenarios como incompletos.

**Límites deliberados de esta primera versión:** el scraper actual extrae la tabla de grupos, no un registro estructurado de retiros, lesiones, descalificaciones, walkovers ni resultados de la fase final. Por eso el módulo no inventa esas circunstancias ni calcula un puesto definitivo del torneo. La clasificación se marca provisional mientras haya partidos pendientes o inconsistencias. Tampoco presenta el objetivo actual como una clasificación matemática asegurada.

El recolector ejecuta `integrar_inteligencia_en_resultado` después de extraer los torneos y antes de guardar en JSON/CSV y memoria histórica. Cada torneo incluye `inteligencia` con clasificación, partidos pendientes, inconsistencias y objetivos reglamentarios; `resumen_inteligencia` agrega conteos del ciclo. Si un torneo no tiene grupos (por ejemplo, Upcoming), se conserva con un análisis vacío. Los errores de análisis se registran en `inteligencia_error` sin detener toda la recolección.

Pruebas del módulo e integración:

```bash
python -m unittest test_inteligencia_torneo.py
```

### Rendimiento en partidos potencialmente decisivos

El análisis incorpora un proxy descriptivo de resultados en partidos cuyo desenlace podía mover al jugador a través del corte competitivo (top 2 en grupos de 4; top 4 en grupos de 5). Se reconstruye la tabla previa retirando temporalmente el duelo y evaluando los escenarios restantes por puntos. No es una medición psicológica de presión ni de puntos decisivos: la fuente actual no entrega secuencias de puntos por set. La tasa se muestra como exploratoria y no se considera muestra suficiente antes de 10 partidos relevantes.

### Acumulado histórico entre torneos

El módulo `historial_rendimiento.py` compara snapshots cronológicos y solo atribuye un partido al contexto competitivo cuando su marcador aparece después de una captura previa comparable. Los resultados que ya estaban presentes en la primera captura se excluyen porque no se conoce la tabla previa. Las métricas se agregan por jugador entre torneos, con número de partidos, victorias, derrotas, tasa y cantidad de torneos con muestra.

Para generar el informe desde la base de datos configurada:

```bash
python historial_rendimiento.py
```

Genera `salida/rendimiento_historico.json`. Se necesitan capturas repetidas mientras los torneos avanzan; una sola captura final no permite reconstruir el contexto previo. Los partidos que aparecen por primera vez en una misma captura comparten el último contexto previo observado. El análisis sigue siendo un proxy competitivo, no una medición psicológica.


## Backfill del archivo histórico oficial

`backfill_historico.py` recorre el listado oficial por días, sigue la paginación observada y descarga la ficha de cada torneo encontrado. Reutiliza el extractor oficial de grupos, resultados, ratings y calendario; reconstruye la secuencia de partidos y guarda cada torneo usando su fecha oficial como marca temporal estable. Repetir un rango actualiza el mismo snapshot en vez de crear una captura duplicada.

### Ejecución

Variables:
- `HISTORICAL_FROM`: inicio inclusivo, `YYYY-MM-DD`; por defecto, doce meses calendario antes de la fecha actual en Praga.
- `HISTORICAL_TO`: fin inclusivo, `YYYY-MM-DD`; por defecto, el día anterior a la fecha actual en Praga.
- Para una ejecución inicial el 18 de noviembre de 2026, el rango predeterminado es del 18 de noviembre de 2025 al 17 de noviembre de 2026.
- `MAX_HISTORICAL_TOURNAMENTS`: límite por ejecución (5000 por defecto; el informe marca si se alcanza antes de terminar el rango).
- `HISTORICAL_PAUSE_SECONDS`: pausa entre fichas (0.25 s por defecto).

Desde GitHub Actions, ejecuta manualmente **Backfill histórico oficial** y suministra el rango. Antes debes configurar el secreto `DATABASE_URL` con la conexión PostgreSQL persistente; el workflow se detiene si falta, para no aparentar que los datos quedan guardados cuando SQLite de Actions se elimina al terminar el trabajo. El diagnóstico JSON se conserva como artefacto durante 14 días.

El backfill es reanudable por rangos: si se interrumpe, vuelve a ejecutar el mismo intervalo o uno menor. El informe indica torneos encontrados/guardados, grupos completos y partidos reconstruidos. Una ficha sin fecha oficial se conserva en el diagnóstico pero no se inserta como histórico.

**Límites de cobertura:** el recolector depende de que el listado público permita consultar ese día y de que la ficha siga disponible. La paginación se sigue hasta `MAX_PAGINAS`; por tanto, los conteos del informe son cobertura observada, no una garantía de que el archivo completo de todos los años se haya descargado. La reconstrucción competitiva utiliza el orden y marcadores publicados; no mide presión psicológica.
