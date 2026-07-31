import sys
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import pandas as pd

from . import amce as amcemod
from . import crosstab as crosstabmod
from . import design_join as designmod
from . import export as exportmod
from . import mapping as mappingmod
from . import reshape as reshapemod
from . import store
from . import vignette as vignettemod
from .readers import read_dataset
from .schema import (
    AmceRequest,
    ConjointMappingConfig,
    BatteryEstimateRequest,
    CrosstabRequest,
    ExperimentCreate,
    ExperimentDuplicate,
    ExperimentUpdate,
    ExternalDesignMappingConfig,
    MultiResponseRequest,
    RecodeRequest,
    SampleFilter,
    TableExportRequest,
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


_KIND_LABELS = {"conjoint": "elección", "vignette": "viñeta", "conjoint_design": "elección con diseño externo"}


def _require_kind(session_id: str, experiment_id: str, kind: str | tuple[str, ...]) -> None:
    allowed = (kind,) if isinstance(kind, str) else kind
    actual = store.get_experiment_kind(session_id, experiment_id)
    if actual not in allowed:
        wanted = " o ".join(f'"{_KIND_LABELS.get(k, k)}"' for k in allowed)
        raise HTTPException(400, f'Este conjunto es de tipo "{_KIND_LABELS.get(actual, actual)}", no {wanted}.')


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


_RECODE_OPERATORS = {
    ">=": lambda s, t: s >= t,
    ">": lambda s, t: s > t,
    "<=": lambda s, t: s <= t,
    "<": lambda s, t: s < t,
    "==": lambda s, t: s == t,
}


@app.post("/api/columns/{session_id}/recode")
async def recode_column(session_id: str, payload: RecodeRequest):
    df = _get_df_or_404(session_id)
    if payload.source_column not in df.columns:
        raise HTTPException(404, f'La columna "{payload.source_column}" no existe en el fichero.')
    if payload.new_column in df.columns:
        raise HTTPException(400, f'Ya existe una columna llamada "{payload.new_column}".')

    numeric = vignettemod.coerce_scale_numeric(df[payload.source_column])
    if numeric.notna().sum() == 0:
        raise HTTPException(400, f'La columna "{payload.source_column}" no tiene ningún valor numérico que recodificar.')

    condition = _RECODE_OPERATORS[payload.operator](numeric, payload.threshold)
    recoded = pd.Series(pd.NA, index=df.index, dtype="object")
    recoded[numeric.notna() & condition] = payload.true_label
    recoded[numeric.notna() & ~condition] = payload.false_label

    label = payload.new_label or f"{payload.new_column} ({payload.source_column} {payload.operator} {payload.threshold:g})"
    store.add_derived_column(session_id, payload.new_column, recoded, label)

    df = store.get_df(session_id)
    labels = store.get_labels(session_id)
    columns = [{"name": c, "label": labels.get(c, c)} for c in df.columns]
    return {"columns": columns, "new_column": payload.new_column}


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
    summary["unmapped_choice_values"] = mappingmod.classify_unmapped_choice_values(df, payload)
    return {"issues": issues, "summary": summary}


@app.get("/api/reshape/{session_id}/{experiment_id}/preview")
async def reshape_preview(session_id: str, experiment_id: str, limit: int = 50):
    long_df = _get_long_df_or_400(session_id, experiment_id)
    preview = long_df.head(limit).copy()
    preview = preview.astype(object).where(preview.notna(), None)
    return {"rows": preview.to_dict(orient="records"), "n_total": int(len(long_df))}


def _download_response(df, fmt: str, filename_stem: str) -> Response:
    try:
        content, content_type = exportmod.export_dataframe(df, fmt)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename_stem}.{fmt}"'},
    )


@app.get("/api/reshape/{session_id}/{experiment_id}/download")
async def download_reshaped(session_id: str, experiment_id: str, format: str = "csv"):
    long_df = _get_long_df_or_400(session_id, experiment_id)
    return _download_response(long_df, format, "conjoint_reestructurado")


@app.post("/api/export/table")
async def export_table(payload: TableExportRequest):
    """Exportación genérica de cualquier tabla ya construida en el cliente
    (no depende de sesión ni de conjunto): coeficientes del AMCE, resultados
    de una estimación por batería, etc."""
    df = pd.DataFrame(payload.rows)
    return _download_response(df, payload.format, payload.filename)


# ---------- Estimación del AMCE (conjuntos de tipo "elección") ----------


@app.post("/api/amce/{session_id}/{experiment_id}")
async def estimate_amce(session_id: str, experiment_id: str, payload: AmceRequest):
    _require_kind(session_id, experiment_id, ("conjoint", "conjoint_design"))
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


@app.get("/api/vignette/{session_id}/{experiment_id}/download")
async def download_vignette(session_id: str, experiment_id: str, format: str = "csv"):
    _require_kind(session_id, experiment_id, "vignette")
    df = _get_long_df_or_400(session_id, experiment_id)
    mapping_config = store.get_experiment_mapping(session_id, experiment_id)
    cols = [mapping_config.outcome_column, *[a.column for a in mapping_config.attributes]]
    cols = [c for c in cols if c in df.columns]
    return _download_response(df[cols], format, "vineta_datos")


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


@app.post("/api/vignette/{session_id}/{experiment_id}/crosstab")
async def vignette_crosstab(session_id: str, experiment_id: str, payload: CrosstabRequest):
    """Tabla cruzada de cada variable de `outcome_columns` por cada atributo
    ya mapeado en este conjunto — no hace falta elegir una única variable de
    resultado ni volver a mapear nada. Relee el fichero filtrado en el
    momento (no la copia guardada al aplicar el mapeo) para que una
    recodificación añadida después también esté disponible."""
    _require_kind(session_id, experiment_id, "vignette")
    _get_long_df_or_400(session_id, experiment_id)  # exige que ya se haya aplicado el mapeo
    mapping_config = store.get_experiment_mapping(session_id, experiment_id)
    df = store.get_filtered_df(session_id, experiment_id)
    labels = store.get_labels(session_id)

    unknown = [c for c in payload.outcome_columns if c not in df.columns]
    if unknown:
        raise HTTPException(400, f"Columna no encontrada: {', '.join(unknown)}.")

    tables = []
    for outcome_col in payload.outcome_columns:
        outcome_label = labels.get(outcome_col, outcome_col)
        for attr in mapping_config.attributes:
            tables.append(
                crosstabmod.build_crosstab(df, outcome_col, outcome_label, attr.column, attr.label or attr.name)
            )
    return {"tables": tables}


@app.post("/api/vignette/{session_id}/{experiment_id}/battery")
async def vignette_battery(session_id: str, experiment_id: str, payload: BatteryEstimateRequest):
    """Regresión de cada variable de `outcome_columns` sobre los atributos ya
    mapeados, una pasada por variable: para experimentos donde el interés no
    es una única variable dependiente sino una batería de preguntas (a
    menudo escalas Likert) sobre el mismo estímulo. Relee el fichero
    filtrado en el momento para que una recodificación añadida después
    también esté disponible."""
    _require_kind(session_id, experiment_id, "vignette")
    df = _get_long_df_or_400(session_id, experiment_id)  # exige que ya se haya aplicado el mapeo
    mapping_config = store.get_experiment_mapping(session_id, experiment_id)
    df = store.get_filtered_df(session_id, experiment_id)
    labels = store.get_labels(session_id)

    unknown_cols = [c for c in payload.outcome_columns if c not in df.columns]
    if unknown_cols:
        raise HTTPException(400, f"Columna no encontrada: {', '.join(unknown_cols)}.")

    attributes = payload.attributes or mapping_config.attribute_names()
    unknown_attrs = [a for a in attributes if a not in mapping_config.attribute_names()]
    if unknown_attrs:
        raise HTTPException(400, f"Atributo no mapeado: {', '.join(unknown_attrs)}.")

    outcome_labels = {c: labels.get(c, c) for c in payload.outcome_columns}
    result = vignettemod.run_vignette_battery(
        df, mapping_config, payload.outcome_columns, outcome_labels, attributes, payload.baselines
    )
    for r in result["results"]:
        r["plot_rows"] = amcemod.to_plot_rows(r)
    return result


@app.post("/api/vignette/{session_id}/{experiment_id}/multi-response")
async def vignette_multi_response(session_id: str, experiment_id: str, payload: MultiResponseRequest):
    """Resumen de un conjunto de respuesta múltiple (p. ej. "¿cuáles crees
    que son los motivos...?" con una columna binaria por motivo), desglosado
    opcionalmente por un atributo ya mapeado en este conjunto."""
    _require_kind(session_id, experiment_id, "vignette")
    _get_long_df_or_400(session_id, experiment_id)
    mapping_config = store.get_experiment_mapping(session_id, experiment_id)
    df = store.get_filtered_df(session_id, experiment_id)

    unknown = [it.column for it in payload.items if it.column not in df.columns]
    if unknown:
        raise HTTPException(400, f"Columna no encontrada: {', '.join(unknown)}.")

    group_column = None
    group_label = None
    if payload.group_attribute:
        attr = next((a for a in mapping_config.attributes if a.name == payload.group_attribute), None)
        if attr is None:
            raise HTTPException(400, f'Atributo no mapeado: "{payload.group_attribute}".')
        group_column, group_label = attr.column, attr.label or attr.name

    items = [{"column": it.column, "label": it.label, "selected_value": it.selected_value} for it in payload.items]
    return crosstabmod.build_multi_response_summary(df, items, group_column, group_label)


# ---------- Mapeo (conjuntos de tipo "elección con diseño externo") ----------


def _get_design_df_or_400(session_id: str, experiment_id: str):
    _get_experiment_or_404(session_id, experiment_id)
    design_df = store.get_experiment_design_df(session_id, experiment_id)
    if design_df is None:
        raise HTTPException(400, "Todavía no se ha subido el fichero de diseño para este conjunto.")
    return design_df


@app.post("/api/design/{session_id}/{experiment_id}/upload")
async def upload_design_file(session_id: str, experiment_id: str, file: UploadFile = File(...)):
    _get_experiment_or_404(session_id, experiment_id)
    _require_kind(session_id, experiment_id, "conjoint_design")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "El archivo supera el límite de 50 MB.")
    try:
        design_df, _ = read_dataset(file.filename, content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"No se pudo leer el archivo: {e}")

    store.set_experiment_design_df(session_id, experiment_id, design_df, file.filename)
    task_profile = designmod.suggest_task_profile_columns(design_df)
    return {
        "filename": file.filename,
        "n_rows": int(design_df.shape[0]),
        "design_columns": list(design_df.columns),
        **task_profile,
    }


@app.get("/api/design/{session_id}/{experiment_id}/design-values")
async def design_column_values(session_id: str, experiment_id: str, column: str, limit: int = 60):
    """Valores distintos de una columna del fichero de diseño, y una
    sugerencia de a qué valor de esos corresponde cada valor observado en
    una columna del fichero de respuestas — para cuando el usuario marca a
    mano una columna del diseño como clave de cruce (las auto-detectadas ya
    vienen con esto resuelto en `/suggest`)."""
    _require_kind(session_id, experiment_id, "conjoint_design")
    design_df = _get_design_df_or_400(session_id, experiment_id)
    if column not in design_df.columns:
        raise HTTPException(404, f'La columna "{column}" no existe en el fichero de diseño.')
    design_values = sorted(design_df[column].astype(str).unique())[:limit]

    respondent_column = None
    value_map: dict[str, str] = {}
    default_design_value = None
    suggested_respondent_column = designmod.suggest_respondent_column_for(column, store.get_filtered_df(session_id, experiment_id))
    if suggested_respondent_column:
        respondent_column = suggested_respondent_column
        value_map, default_design_value = designmod.suggest_value_map(
            store.get_filtered_df(session_id, experiment_id), respondent_column, design_values
        )

    return {
        "design_values": design_values,
        "suggested_respondent_column": respondent_column,
        "value_map": value_map,
        "default_design_value": default_design_value,
    }


@app.get("/api/design/{session_id}/{experiment_id}/value-map-suggestion")
async def design_value_map_suggestion(session_id: str, experiment_id: str, respondent_column: str, design_column: str):
    """Recalcula la sugerencia de correspondencia de valores cuando el
    usuario elige a mano una columna de respuestas distinta a la sugerida
    inicialmente para una clave de cruce."""
    _require_kind(session_id, experiment_id, "conjoint_design")
    respondent_df = store.get_filtered_df(session_id, experiment_id)
    design_df = _get_design_df_or_400(session_id, experiment_id)
    if respondent_column not in respondent_df.columns:
        raise HTTPException(404, f'La columna "{respondent_column}" no existe en el fichero de respuestas.')
    if design_column not in design_df.columns:
        raise HTTPException(404, f'La columna "{design_column}" no existe en el fichero de diseño.')
    design_values = sorted(design_df[design_column].astype(str).unique())
    value_map, default_design_value = designmod.suggest_value_map(respondent_df, respondent_column, design_values)
    return {"design_values": design_values, "value_map": value_map, "default_design_value": default_design_value}


@app.get("/api/design/{session_id}/{experiment_id}/suggest")
async def suggest_design_mapping(session_id: str, experiment_id: str, task_column: str, profile_column: str):
    _require_kind(session_id, experiment_id, "conjoint_design")
    respondent_df = store.get_filtered_df(session_id, experiment_id)
    design_df = _get_design_df_or_400(session_id, experiment_id)

    if task_column not in design_df.columns or profile_column not in design_df.columns:
        raise HTTPException(400, "La columna de tarea o de perfil no existe en el fichero de diseño.")

    tasks = sorted(design_df[task_column].astype(str).unique(), key=lambda x: (len(x), x))
    profiles = sorted(design_df[profile_column].astype(str).unique())

    remaining = designmod.suggest_remaining_columns(design_df, task_column, profile_column)
    join_candidates = designmod.suggest_join_key_columns(design_df, respondent_df, remaining)

    choice_columns = designmod.suggest_choice_columns(respondent_df, tasks)
    choice_value_map, unmatched_choice_values = mappingmod.infer_choice_value_map(respondent_df, choice_columns, profiles)

    join_key_suggestions = []
    for design_col in join_candidates:
        resp_col = designmod.suggest_respondent_column_for(design_col, respondent_df)
        design_values = sorted(design_df[design_col].astype(str).unique())
        value_map, default_value = ({}, None)
        if resp_col:
            value_map, default_value = designmod.suggest_value_map(respondent_df, resp_col, design_values)
        join_key_suggestions.append({
            "design_column": design_col,
            "respondent_column": resp_col,
            "design_values": design_values,
            "value_map": value_map,
            "default_design_value": default_value,
        })

    return {
        "tasks": tasks,
        "profiles": profiles,
        "remaining_columns": remaining,
        "join_key_candidates": join_key_suggestions,
        "choice_columns": choice_columns,
        "choice_value_map": choice_value_map,
        "unmatched_choice_values": unmatched_choice_values,
    }


@app.post("/api/design/{session_id}/{experiment_id}/apply")
async def apply_design_mapping(session_id: str, experiment_id: str, payload: ExternalDesignMappingConfig):
    _get_experiment_or_404(session_id, experiment_id)
    _require_kind(session_id, experiment_id, "conjoint_design")
    respondent_df = store.get_filtered_df(session_id, experiment_id)
    design_df = _get_design_df_or_400(session_id, experiment_id)

    issues = designmod.validate_external_design_config(respondent_df, design_df, payload)

    try:
        long_df = designmod.build_long_df(respondent_df, design_df, payload)
    except Exception as e:
        raise HTTPException(400, f"No se pudo cruzar el diseño con las respuestas: {e}")

    store.set_experiment_mapping(session_id, experiment_id, payload, long_df)
    summary = reshapemod.reshape_summary(long_df, payload)
    return {"issues": issues, "summary": summary}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")
