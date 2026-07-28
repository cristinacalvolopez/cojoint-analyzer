# Cojoint Analyzer

Aplicación web para analizar experimentos de elección conjunta (conjoint)
sobre actitudes hacia la comunidad LGTBIQ+: mapea interactivamente las
variables de un fichero en formato ancho, lo reestructura a formato largo
(tidy) y estima el Efecto Marginal Medio (AMCE) por OLS con errores
agrupados por individuo o por logit condicional, con un dot plot
exportable listo para publicación.

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
│   static/app.js      │◄────┤  FastAPI: upload · mapping · reshape ·    │
│   static/styles.css  │ REST│  amce · sesión en memoria (store.py)      │
└─────────────────────┘      └───────────────┬────────────────────────────┘
                                              │
                     ┌────────────────────────┼─────────────────────────┐
                     ▼                        ▼                         ▼
              app/readers.py           app/mapping.py            app/amce.py
              xlsx/csv/dta/sav         detección automática      OLS clustered
              + etiquetas Stata/SPSS   + validación del mapeo    + logit condicional
                                              │
                                              ▼
                                        app/reshape.py
                                        motor wide -> long
```

### Flujo funcional (wizard de 3 pasos)

1. **Mapeo de variables** (`app/mapping.py`, `app/schema.py`): al subir el
   archivo, `suggest_mapping()` reconoce por regex el patrón
   `<tarea>_<perfil>_<atributo>` (p. ej. `cj1_A_gen`, `cj3_B_ca_1`) y la
   columna de elección de cada tarea (`cj1_eleccion`, `cj1_elige`…), y
   propone una configuración inicial (`ConjointMappingConfig`). El usuario
   la revisa y corrige en una rejilla editable antes de continuar — nunca
   se reestructura a ciegas.
2. **Reestructuración** (`app/reshape.py`): pivota el fichero ancho a
   formato largo, una fila por perfil evaluado, con `respondent_id`,
   `task`, `profile`, `choice_set` (necesario para el clogit) y `chosen`
   (0/1). Se valida que cada conjunto de elección tenga exactamente un
   perfil marcado como elegido y se informa de incidencias (valores
   perdidos, elecciones ambiguas).
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
- CSV/xlsx no tienen este concepto: la etiqueta coincide con el nombre de
  columna.

## Esquema de directorios

```
cojoint-analyzer/
├── app/
│   ├── main.py         # rutas FastAPI
│   ├── readers.py      # lectura de xlsx / csv / dta / sav (datos y etiquetas)
│   ├── schema.py        # modelos pydantic del mapeo (ConjointMappingConfig...)
│   ├── mapping.py       # detección automática + validación del mapeo
│   ├── reshape.py       # motor de transformación wide -> long
│   ├── amce.py           # estimación AMCE (OLS clustered / clogit)
│   └── store.py          # sesiones en memoria (dataset, mapeo, fichero largo)
├── static/
│   ├── index.html
│   ├── styles.css        # mismos design tokens que pretest-analyzer
│   └── app.js             # SPA sin build step (upload, wizard, dot plot SVG, export)
├── tests/
│   ├── conftest.py        # generador de datos wide sintéticos con efecto conocido
│   ├── test_reshape.py
│   └── test_amce.py
├── sample_data/
│   └── generate_sample.py # genera un CSV ancho de ejemplo (300 x 8 tareas x 2 perfiles)
├── requirements.txt
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
para probar el flujo completo.

### Tests

```bash
pytest
```

Los tests generan datos sintéticos con un efecto conocido en un atributo
(`role_effect`) y comprueban que tanto el OLS clustered como el logit
condicional lo recuperan con el signo y la significatividad esperados —
no solo que el código no lance excepciones.

## Extender a los experimentos de viñetas

La base también incluye dos experimentos de viñeta (gravedad de agresiones,
eficacia de leyes). No comparten la estructura de perfiles enfrentados del
conjoint, así que no reutilizan `reshape.py`/`amce.py` tal cual, pero
encajan en la misma arquitectura: un lector de datos ya común
(`readers.py`), un módulo de mapeo propio (p. ej. `app/vignette.py`) y un
paso adicional en el wizard de `static/app.js`. Se ha dejado fuera del
alcance inicial para no sobre-construir antes de tener claro el diseño
exacto de esas viñetas.

## Notas de despliegue

- Sin base de datos ni almacenamiento persistente: cada sesión vive en
  memoria del proceso durante 4 horas como máximo (`app/store.py`),
  deliberado porque la base contiene datos de entrevistas sensibles.
- Límite de subida: 50 MB por archivo (`MAX_UPLOAD_BYTES` en `app/main.py`).
- Para producción, ejecuta detrás de un proceso manager (`uvicorn` con
  `--workers`, o un servicio systemd/Docker) y sin `--reload`.
