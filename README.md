# Cojoint Analyzer

Aplicación web para analizar experimentos de elección conjunta (conjoint) y
de viñeta sobre actitudes hacia la comunidad LGTBIQ+: detecta y mapea las
variables de un fichero en formato ancho, reestructura a formato largo
(tidy) cuando hace falta y estima el efecto de cada atributo —AMCE por OLS
clustered/logit condicional para elección, OLS para viñeta— con un dot plot
exportable listo para publicación.

Un mismo fichero puede contener más de un experimento (p. ej. un conjoint de
elección y una o varias viñetas administradas a submuestras distintas de la
misma encuesta): la sesión no está limitada a un único mapeo, sino a una
colección de **conjuntos**, cada uno con su propio tipo, su propio filtro de
submuestra opcional y su propio mapeo/resultado independientes.

Los datos se procesan solo en memoria mientras la aplicación está en
marcha; no se escriben en disco ni se envían a ningún servidor externo.

## Arquitectura

Mismo patrón que [`pretest-analyzer`](https://github.com/cristinacalvolopez/pretest-analyzer):
un backend FastAPI sin estado persistente (sesión en memoria, TTL de 4h) que
sirve una SPA estática sin build step (HTML + CSS + un único `app.js`, sin
framework ni bundler). La estética —tokens de color, tipografía, cards,
tabs, sidebar, modal, checklist, badges— se reutiliza literalmente de ese
repositorio para que ambas herramientas se sientan como parte de la misma
suite.

```
┌─────────────────────┐      ┌──────────────────────────────────────────┐
│   static/index.html │      │                 app/main.py               │
│   static/app.js      │◄────┤  FastAPI: upload · experiments · mapping  │
│   static/styles.css  │ REST│  · reshape · amce/vignette (store.py)     │
└─────────────────────┘      └───────────────┬────────────────────────────┘
                                              │
                ┌─────────────────┬───────────┼───────────┬─────────────────┐
                ▼                 ▼           ▼           ▼                 ▼
         app/readers.py    app/mapping.py  app/reshape.py app/amce.py  app/vignette.py
         xlsx/csv/dta/sav  detección       wide -> long   OLS clustered mapeo + OLS
         + etiquetas       automática      (conjoint)     + logit      de viñeta
         Stata/SPSS        + choice_value_map                condicional (sin reshape)
         (acentos          contra valores reales
         corregidos)
```

### Conjuntos: varios experimentos por sesión

`app/store.py` guarda, por sesión, el dataframe original **y una colección
de conjuntos** (no un único mapeo). Cada conjunto tiene:

- Un **tipo**: `conjoint` (elección entre perfiles enfrentados) o
  `vignette` (perfil/estímulo único, valorado en una variable de resultado).
- Un **filtro de submuestra** opcional (`SampleFilter`: columna + valores),
  para restringir el conjunto a las filas de una columna tipo `EXPERIMENTO`
  cuando el fichero reparte varios experimentos entre distintas submuestras
  de la misma encuesta.
- Su propio mapeo y, para conjoint, el fichero largo ya reestructurado.

La interfaz (`static/app.js`) muestra un panel "Conjuntos" en la barra
lateral (crear, renombrar, duplicar como plantilla, eliminar) y adapta el
asistente de pasos al tipo del conjunto activo.

### Flujo funcional — conjuntos de tipo "elección" (conjoint)

1. **Mapeo de variables** (`app/mapping.py`, `app/schema.py`): al subir el
   archivo, `suggest_mapping()` reconoce por regex el patrón
   `<tarea>_<perfil>_<atributo>` (p. ej. `cj1_A_gen`, `cj3_B_ca_1`) y la
   columna de elección de cada tarea (`cj1_eleccion`, `cj1_elige`…), y
   propone una configuración inicial (`ConjointMappingConfig`). Además,
   `infer_choice_value_map()` deduce a qué perfil corresponde cada valor
   *realmente observado* en la columna de elección (coincidencia exacta →
   token suelto dentro del valor → posición por el número final), en vez de
   asumir que el valor crudo es literalmente "A"/"B": Stata/SPSS casi
   siempre lo convierten a su etiqueta completa ("Perfil A", "Candidato/a
   1"...). El usuario revisa y corrige en una rejilla editable — tareas y
   perfiles se añaden/quitan como chips desde listas de candidatos
   detectados en el propio fichero, nunca escribiendo un nombre a mano.
2. **Reestructuración** (`app/reshape.py`): pivota el fichero ancho (ya
   recortado por el filtro de submuestra, si lo hay) a formato largo, una
   fila por perfil evaluado, con `respondent_id`, `task`, `profile`,
   `choice_set` (necesario para el clogit) y `chosen` (0/1). Se valida que
   cada conjunto de elección tenga exactamente un perfil marcado como
   elegido y se informa de incidencias (valores perdidos, elecciones
   ambiguas).
3. **Estimación del AMCE** (`app/amce.py`): sobre el fichero largo,
   - `ols`: `chosen ~ dummies de cada atributo` por mínimos cuadrados con
     errores estándar *cluster-robust* agrupados por entrevistado
     (`cov_type="cluster"`), el estimador estándar del AMCE (Hainmueller,
     Hopkins & Yamamoto, 2014).
   - `clogit`: logit condicional (`statsmodels.discrete.conditional_models.ConditionalLogit`)
     dentro de cada conjunto de elección, explotando directamente el
     diseño de elección forzada.
   El resultado se sirve ya listo para graficar (`plot_rows`, con la
   categoría de referencia incluida en `estimate = 0`) y la tabla de
   coeficientes completa con IC 95% y p-valor.

### Flujo funcional — conjuntos de tipo "viñeta"

A diferencia del conjoint, en una viñeta cada entrevistado ve un único
perfil o estímulo (a menudo aleatorizado entre unas pocas versiones, p. ej.
"Texto A"/"Texto B") y lo valora en una variable de resultado continua o de
escala, no elige entre dos. No hay perfiles enfrentados, así que
`app/vignette.py` no reutiliza `reshape.py`: cada fila del fichero ancho ya
es una observación completa.

1. **Mapeo** (`suggest_outcome_columns`/`suggest_attribute_columns`):
   sugiere qué columnas parecen variable de resultado (numéricas, recorrido
   amplio, no un identificador de entrevistado) y cuáles atributo del
   estímulo (pocos niveles distintos). Son solo una ordenación por defecto
   — el selector siempre permite elegir cualquier columna del fichero,
   agrupada en "Sugeridas" / "Todas las demás", precisamente porque este
   heurístico puede fallar (p. ej. una escala 0–10 con techo, donde casi
   todos contestan el máximo y apenas se observan 3–4 valores distintos en
   una submuestra pequeña).
   `_coerce_scale_numeric()` además recupera escalas donde SPSS/Stata solo
   etiquetan los extremos (código 10 → texto "10 Muy grave", código 0 →
   "0 Nada grave") dejando los códigos intermedios como número puro: una
   conversión numérica directa perdería justo esos extremos, que suelen ser
   las respuestas más frecuentes.
2. **Estimación** (`run_vignette_ols`): OLS del resultado sobre dummies de
   cada atributo, con errores robustos (`cov_type="HC1"`); mismo formato de
   coeficientes que el AMCE, así que reutiliza el mismo dot plot y tabla.

### Manejo de metadatos y etiquetas (Stata/SPSS)

`app/readers.py` sigue las mismas prácticas que `pretest-analyzer`:

- Conserva la etiqueta descriptiva de variable (`variable_labels()` en
  Stata, `column_labels` en SPSS) por separado del nombre técnico de
  columna, para mostrarla en la interfaz.
- Aplica las etiquetas de valor (1/2 -> "Hombre"/"Mujer") y conserva el
  **orden original** de las categorías (`formats_as_ordered_category=True`
  en SPSS; reconstrucción manual del orden en Stata), en vez de dejar que
  pandas reordene alfabéticamente.
- Cuando dos códigos distintos de Stata comparten el mismo texto de
  etiqueta, los distingue añadiendo el código entre paréntesis en vez de
  fallar al construir la categórica.
- Repara acentos corruptos (`_fix_mojibake`): los `.dta` con formato < 118
  (Stata < 15) no declaran su propia codificación y pandas asume latin-1,
  pero en la práctica muchos de estos ficheros contienen texto en UTF-8
  (p. ej. si se generaron o reexportaron con herramientas no-Stata). El
  síntoma es "uÃ±as" en vez de "uñas"; se corrige solo cuando reinterpretar
  el texto como UTF-8 tiene éxito, la señal inequívoca de que hubo doble
  decodificación — si no, se deja el texto tal cual.
- CSV/xlsx no tienen este concepto: la etiqueta coincide con el nombre de
  columna.

## Esquema de directorios

```
cojoint-analyzer/
├── app/
│   ├── main.py         # rutas FastAPI (sesión, conjuntos, mapping/reshape/amce, vignette)
│   ├── readers.py      # lectura de xlsx / csv / dta / sav (datos, etiquetas, fix de acentos)
│   ├── schema.py        # modelos pydantic (ConjointMappingConfig, VignetteMappingConfig, SampleFilter...)
│   ├── mapping.py       # detección automática (conjoint) + validación del mapeo
│   ├── reshape.py       # motor de transformación wide -> long (conjoint)
│   ├── amce.py           # estimación AMCE (OLS clustered / clogit) + utilidades compartidas
│   ├── vignette.py       # detección, validación y estimación OLS para conjuntos de viñeta
│   └── store.py          # sesiones en memoria: dataset + colección de conjuntos
├── static/
│   ├── index.html
│   ├── styles.css        # mismos design tokens que pretest-analyzer
│   └── app.js             # SPA sin build step (conjuntos, mapeo, dot plot SVG, export)
├── tests/
│   ├── conftest.py        # generador de datos wide sintéticos con efecto conocido
│   ├── test_reshape.py
│   ├── test_amce.py
│   ├── test_mapping.py
│   ├── test_readers.py    # fix de acentos corruptos (mojibake)
│   ├── test_vignette.py
│   └── test_api.py        # integración: varios conjuntos por sesión, filtro, viñeta
├── sample_data/
│   └── generate_sample.py # genera un CSV ancho de ejemplo (300 x 8 tareas x 2 perfiles)
├── requirements.txt
├── requirements-dev.txt   # + pytest/httpx, para correr la suite de tests
└── .gitignore
```

## Cómo empezar

Requiere Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# (opcional) genera un dataset de ejemplo con la misma forma que el estudio real
python sample_data/generate_sample.py

uvicorn app.main:app --reload
```

Abre [http://localhost:8000](http://localhost:8000) y sube
`sample_data/conjoint_sample_wide.csv` (o tu `.dta`/`.sav`/`.xlsx` real)
para probar el flujo completo. Al subir el archivo se crea un primer
conjunto de tipo elección con la sugerencia ya aplicada; usa el botón "+"
del panel "Conjuntos" para añadir más (p. ej. una viñeta, o el mismo tipo
filtrado a otra submuestra).

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Los tests generan datos sintéticos con un efecto conocido en un atributo
(`role_effect`) y comprueban que tanto el OLS clustered como el logit
condicional lo recuperan con el signo y la significatividad esperados —
no solo que el código no lance excepciones. `test_api.py` cubre además el
modelo de varios conjuntos por sesión (filtro de submuestra, viñeta,
duplicar/eliminar) con el `TestClient` de FastAPI.

## Notas de despliegue

- Sin base de datos ni almacenamiento persistente: cada sesión vive en
  memoria del proceso durante 4 horas como máximo (`app/store.py`),
  deliberado porque la base contiene datos de entrevistas sensibles.
- Límite de subida: 50 MB por archivo (`MAX_UPLOAD_BYTES` en `app/main.py`).
- Para producción, ejecuta detrás de un proceso manager (`uvicorn` con
  `--workers`, o un servicio systemd/Docker) y sin `--reload`.

## Fuera de alcance por ahora

Algunos experimentos de elección exportan solo la respuesta (qué perfil
ganó cada pantalla) y una columna de versión/bloque de diseño, sin incrustar
los atributos de cada perfil como columnas del fichero de respondientes: el
diseño real vive en un fichero de bloques aparte, keyed por versión × tarea
× perfil. Sin ese fichero de diseño no hay manera de calcular un AMCE para
ese experimento — la app lo señala como "0 atributos detectados" en el paso
de mapeo, pero unir un fichero de diseño externo queda fuera del alcance
actual.
