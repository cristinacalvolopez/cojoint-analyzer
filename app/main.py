import sys
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import amce as amcemod
from . import mapping as mappingmod
from . import reshape as reshapemod
from . import store
from .readers import read_dataset
from .schema import AmceRequest, ConjointMappingConfig

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

app = FastAPI(title="Cojoint Analyzer")


def _get_df_or_404(session_id: str):
    try:
        return store.get_df(session_id)
    except KeyError as e:
        raise HTTPException(404, str(e))


def _get_long_df_or_400(session_id: str):
    _get_df_or_404(session_id)
    long_df = store.get_long_df(session_id)
    if long_df is None:
        raise HTTPException(400, "Todavía no se ha aplicado un mapeo de variables para este archivo.")
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
    return {
        "session_id": session_id,
        "filename": file.filename,
        "n_rows": int(df.shape[0]),
        "n_cols": int(df.shape[1]),
        "columns": columns,
        "suggested_mapping": mappingmod.suggest_mapping(list(df.columns)),
    }


@app.get("/api/variables/{session_id}")
async def variables(session_id: str):
    df = _get_df_or_404(session_id)
    labels = store.get_labels(session_id)
    columns = [{"name": c, "label": labels.get(c, c)} for c in df.columns]
    return {"n_rows": int(df.shape[0]), "columns": columns}


@app.delete("/api/session/{session_id}")
async def remove_session(session_id: str):
    store.delete_session(session_id)
    return {"ok": True}


# ---------- Mapeo y reestructuración ----------


@app.get("/api/mapping/{session_id}/suggest")
async def suggest_mapping(session_id: str):
    df = _get_df_or_404(session_id)
    return mappingmod.suggest_mapping(list(df.columns))


@app.post("/api/mapping/{session_id}/apply")
async def apply_mapping(session_id: str, payload: ConjointMappingConfig):
    df = _get_df_or_404(session_id)

    issues = mappingmod.validate_config(df, payload)

    try:
        long_df = reshapemod.wide_to_long(df, payload)
    except Exception as e:
        raise HTTPException(400, f"No se pudo reestructurar el fichero: {e}")

    store.set_mapping(session_id, payload, long_df)
    summary = reshapemod.reshape_summary(long_df, payload)
    return {"issues": issues, "summary": summary}


@app.get("/api/reshape/{session_id}/preview")
async def reshape_preview(session_id: str, limit: int = 50):
    long_df = _get_long_df_or_400(session_id)
    preview = long_df.head(limit).copy()
    preview = preview.astype(object).where(preview.notna(), None)
    return {"rows": preview.to_dict(orient="records"), "n_total": int(len(long_df))}


# ---------- Estimación del AMCE ----------


@app.post("/api/amce/{session_id}")
async def estimate_amce(session_id: str, payload: AmceRequest):
    long_df = _get_long_df_or_400(session_id)
    mapping_config = store.get_mapping(session_id)

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


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")
