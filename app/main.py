import sys
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import amce as amcemod
from . import mapping as mappingmod
from . import reshape as reshapemod
from . import store
from . import vignette as vignettemod
from .readers import read_dataset
from .schema import (
    AmceRequest,
    ConjointMappingConfig,
    ExperimentCreate,
    ExperimentDuplicate,
    ExperimentUpdate,
    SampleFilter,
    VignetteEstimateRequest,
    VignetteMappingConfig,
)

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
DEFAULT_EXPERIMENT_NAME = "Conjunto 1"

app = FastAPI(title="Cojoint Analyzer")


def _get_df_or_404(session_id: str):
    try:
        return store.get_df(session_id)
    except KeyError as e:
        raise HTTPException(404, str(e))


def _get_experiment_or_404(session_id: str, experiment_id: str) -> dict:
    _get_df_or_404(session_id)
    try:
        return store.get_experiment_summary(session_id, experiment_id)
    except KeyError as e:
        raise HTTPException(404, str(e))


def _require_kind(session_id: str, experiment_id: str, kind: str) -> None:
    actual = store.get_experiment_kind(session_id, experiment_id)
    if actual != kind:
        labels = {"conjoint": "elección", "vignette": "viñeta"}
        raise HTTPException(
            400,
            f'Este conjunto es de tipo "{labels.get(actual, actual)}", no "{labels.get(kind, kind)}".',
        )


def _get_long_df_or_400(session_id: str, experiment_id: str):
    _get_experiment_or_404(session_id, experiment_id)
    long_df = store.get_experiment_long_df(session_id, experiment_id)
    if long_df is None:
        raise HTTPException(400, "Todavía no se ha aplicado un mapeo de variables para este conjunto.")
    return long_df


# ---------- Carga de datos ----------


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "El archivo supera el límite de 50 MB.")

    try:
        df, labels = read_dataset(file.filename, content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"No se pudo leer el archivo: {e}")

    if df.shape[1] == 0:
        raise HTTPException(400, "El archivo no contiene columnas.")

    session_id = store.create_session(df, file.filename, labels)
    columns = [{"name": c, "label": labels.get(c, c)} for c in df.columns]

    experiment_id = store.create_experiment(session_id, DEFAULT_EXPERIMENT_NAME, "conjoint")
    suggested_mapping = mappingmod.suggest_mapping(list(df.columns), df)

    return {
        "session_id": session_id,
        "filename": file.filename,
        "n_rows": int(df.shape[0]),
        "n_cols": int(df.shape[1]),
        "columns": columns,
        "experiments": store.list_experiments(session_id),
        "default_experiment_id": experiment_id,
        "suggested_mapping": suggested_mapping,
    }


@app.get("/api/variables/{session_id}")
async def variables(session_id: str):
    df = _get_df_or_404(session_id)
    labels = store.get_labels(session_id)
    columns = [{"name": c, "label": labels.get(c, c)} for c in df.columns]
    return {"n_rows": int(df.shape[0]), "columns": columns}


@app.get("/api/columns/{session_id}/values")
async def column_values(session_id: str, column: str, limit: int = 50):
    df = _get_df_or_404(session_id)
    if column not in df.columns:
        raise HTTPException(404, f'La columna "{column}" no existe en el fichero.')
    counts = df[column].astype(str).value_counts(dropna=False)
    values = [{"value": v, "n": int(n)} for v, n in counts.items()]
    return {"values": values[:limit], "n_distinct": int(len(counts))}


@app.delete("/api/session/{session_id}")
async def remove_session(session_id: str):
    store.delete_session(session_id)
    return {"ok": True}


# ---------- Conjuntos (experimentos) ----------


@app.get("/api/experiments/{session_id}")
async def list_experiments(session_id: str):
    _get_df_or_404(session_id)
    return {"experiments": store.list_experiments(session_id)}


@app.post("/api/experiments/{session_id}")
async def create_experiment(session_id: str, payload: ExperimentCreate):
    _get_df_or_404(session_id)
    experiment_id = store.create_experiment(session_id, payload.name, payload.kind, payload.sample_filter)
    return store.get_experiment_summary(session_id, experiment_id)


@app.patch("/api/experiments/{session_id}/{experiment_id}")
async def update_experiment(session_id: str, experiment_id: str, payload: ExperimentUpdate):
    _get_experiment_or_404(session_id, experiment_id)
    if payload.name is not None:
        store.rename_experiment(session_id, experiment_id, payload.name)
    if payload.clear_sample_filter:
        store.set_experiment_filter(session_id, experiment_id, None)
    elif payload.sample_filter is not None:
        store.set_experiment_filter(session_id, experiment_id, payload.sample_filter)
    return store.get_experiment_summary(session_id, experiment_id)


@app.post("/api/experiments/{session_id}/{experiment_id}/duplicate")
async def duplicate_experiment(session_id: str, experiment_id: str, payload: ExperimentDuplicate):
    _get_experiment_or_404(session_id, experiment_id)
    new_id = store.duplicate_experiment(session_id, experiment_id, payload.name)
    return store.get_experiment_summary(session_id, new_id)


@app.delete("/api/experiments/{session_id}/{experiment_id}")
async def remove_experiment(session_id: str, experiment_id: str):
    _get_experiment_or_404(session_id, experiment_id)
    store.delete_experiment(session_id, experiment_id)
    return {"ok": True}


# ---------- Mapeo y reestructuración (conjuntos de tipo "elección") ----------


@app.get("/api/mapping/{session_id}/{experiment_id}/suggest")
async def suggest_mapping(session_id: str, experiment_id: str):
    _get_experiment_or_404(session_id, experiment_id)
    _require_kind(session_id, experiment_id, "conjoint")
    df = store.get_filtered_df(session_id, experiment_id)
    return mappingmod.suggest_mapping(list(df.columns), df)


@app.post("/api/mapping/{session_id}/{experiment_id}/apply")
async def apply_mapping(session_id: str, experiment_id: str, payload: ConjointMappingConfig):
    _get_experiment_or_404(session_id, experiment_id)
    _require_kind(session_id, experiment_id, "conjoint")
    df = store.get_filtered_df(session_id, experiment_id)

    issues = mappingmod.validate_config(df, payload)

    try:
        long_df = reshapemod.wide_to_long(df, payload)
    except Exception as e:
        raise HTTPException(400, f"No se pudo reestructurar el fichero: {e}")

    store.set_experiment_mapping(session_id, experiment_id, payload, long_df)
    summary = reshapemod.reshape_summary(long_df, payload)
    return {"issues": issues, "summary": summary}


@app.get("/api/reshape/{session_id}/{experiment_id}/preview")
async def reshape_preview(session_id: str, experiment_id: str, limit: int = 50):
    long_df = _get_long_df_or_400(session_id, experiment_id)
    preview = long_df.head(limit).copy()
    preview = preview.astype(object).where(preview.notna(), None)
    return {"rows": preview.to_dict(orient="records"), "n_total": int(len(long_df))}


# ---------- Estimación del AMCE (conjuntos de tipo "elección") ----------


@app.post("/api/amce/{session_id}/{experiment_id}")
async def estimate_amce(session_id: str, experiment_id: str, payload: AmceRequest):
    _require_kind(session_id, experiment_id, "conjoint")
    long_df = _get_long_df_or_400(session_id, experiment_id)
    mapping_config = store.get_experiment_mapping(session_id, experiment_id)

    attributes = payload.attributes or mapping_config.attribute_names()
    unknown = [a for a in attributes if a not in mapping_config.attribute_names()]
    if unknown:
        raise HTTPException(400, f"Atributo no mapeado: {', '.join(unknown)}.")

    try:
        result = amcemod.run_amce(long_df, payload.method, attributes, payload.baselines)
    except ValueError as e:
        raise HTTPException(400, str(e))

    result["plot_rows"] = amcemod.to_plot_rows(result)
    return result


# ---------- Mapeo y estimación (conjuntos de tipo "viñeta") ----------


@app.get("/api/vignette/{session_id}/{experiment_id}/suggest")
async def suggest_vignette(session_id: str, experiment_id: str):
    _get_experiment_or_404(session_id, experiment_id)
    _require_kind(session_id, experiment_id, "vignette")
    labels = store.get_labels(session_id)
    df = store.get_filtered_df(session_id, experiment_id)
    return {
        "candidate_outcome_columns": vignettemod.suggest_outcome_columns(df, labels),
        "candidate_attribute_columns": vignettemod.suggest_attribute_columns(df, labels),
    }


@app.post("/api/vignette/{session_id}/{experiment_id}/apply")
async def apply_vignette(session_id: str, experiment_id: str, payload: VignetteMappingConfig):
    _get_experiment_or_404(session_id, experiment_id)
    _require_kind(session_id, experiment_id, "vignette")
    df = store.get_filtered_df(session_id, experiment_id)

    issues = vignettemod.validate_vignette_config(df, payload)
    store.set_experiment_mapping(session_id, experiment_id, payload, df)

    n_valid = 0
    cols = [payload.outcome_column, *[a.column for a in payload.attributes]]
    cols = [c for c in cols if c in df.columns]
    if cols:
        n_valid = int(df[cols].dropna().shape[0])

    return {"issues": issues, "summary": {"n_rows": int(df.shape[0]), "n_valid_rows": n_valid}}


@app.get("/api/vignette/{session_id}/{experiment_id}/preview")
async def vignette_preview(session_id: str, experiment_id: str, limit: int = 50):
    _require_kind(session_id, experiment_id, "vignette")
    df = _get_long_df_or_400(session_id, experiment_id)
    mapping_config = store.get_experiment_mapping(session_id, experiment_id)
    cols = [mapping_config.outcome_column, *[a.column for a in mapping_config.attributes]]
    cols = [c for c in cols if c in df.columns]
    preview = df[cols].head(limit).copy()
    preview = preview.astype(object).where(preview.notna(), None)
    return {"rows": preview.to_dict(orient="records"), "n_total": int(len(df))}


@app.post("/api/vignette/{session_id}/{experiment_id}/estimate")
async def estimate_vignette(session_id: str, experiment_id: str, payload: VignetteEstimateRequest):
    _require_kind(session_id, experiment_id, "vignette")
    df = _get_long_df_or_400(session_id, experiment_id)
    mapping_config = store.get_experiment_mapping(session_id, experiment_id)

    attributes = payload.attributes or mapping_config.attribute_names()
    unknown = [a for a in attributes if a not in mapping_config.attribute_names()]
    if unknown:
        raise HTTPException(400, f"Atributo no mapeado: {', '.join(unknown)}.")

    restricted_config = mapping_config.model_copy(
        update={"attributes": [a for a in mapping_config.attributes if a.name in attributes]}
    )

    try:
        result = vignettemod.run_vignette_ols(df, restricted_config, payload.baselines)
    except ValueError as e:
        raise HTTPException(400, str(e))

    result["plot_rows"] = amcemod.to_plot_rows(result)
    return result


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")
