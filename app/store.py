"""Almacén en memoria de los datasets subidos y de sus "conjuntos"
(experimentos) de análisis, indexados por sesión.

Un mismo fichero puede contener más de un experimento (p. ej. un conjoint de
elección y una o varias viñetas administradas a submuestras distintas), así
que cada sesión guarda un dataframe original y una colección de conjuntos;
cada conjunto tiene su propio tipo, su propio filtro de submuestra opcional
(p. ej. `EXPERIMENTO = 1`) y su propio mapeo/resultado, independientes entre
sí.

No hay persistencia en disco ni base de datos: los datos viven solo mientras
el proceso está en marcha, lo cual es deliberado dado que la base contiene
datos de entrevistas sobre LGTBI+.
"""
import time
import uuid

import pandas as pd

from .schema import ConjointMappingConfig, SampleFilter, VignetteMappingConfig

SESSION_TTL_SECONDS = 4 * 60 * 60  # 4 horas

_SESSIONS: dict[str, dict] = {}


def _purge_expired() -> None:
    now = time.time()
    expired = [sid for sid, s in _SESSIONS.items() if now - s["created"] > SESSION_TTL_SECONDS]
    for sid in expired:
        _SESSIONS.pop(sid, None)


def _get_record(session_id: str) -> dict:
    _purge_expired()
    session = _SESSIONS.get(session_id)
    if session is None:
        raise KeyError("Sesión no encontrada o expirada. Vuelve a subir el archivo.")
    return session


def create_session(df: pd.DataFrame, filename: str, labels: dict[str, str] | None = None) -> str:
    _purge_expired()
    session_id = uuid.uuid4().hex
    _SESSIONS[session_id] = {
        "df": df,
        "filename": filename,
        "created": time.time(),
        "labels": dict(labels or {}),
        "experiments": {},
    }
    return session_id


def get_df(session_id: str) -> pd.DataFrame:
    return _get_record(session_id)["df"]


def get_labels(session_id: str) -> dict[str, str]:
    return _get_record(session_id)["labels"]


def delete_session(session_id: str) -> None:
    _SESSIONS.pop(session_id, None)


# ---------- Conjuntos (experimentos) ----------


def _new_experiment_record(name: str, kind: str, sample_filter: SampleFilter | None = None) -> dict:
    return {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "kind": kind,
        "sample_filter": sample_filter,
        "mapping": None,
        "long_df": None,
    }


def create_experiment(session_id: str, name: str, kind: str = "conjoint", sample_filter: SampleFilter | None = None) -> str:
    session = _get_record(session_id)
    record = _new_experiment_record(name, kind, sample_filter)
    session["experiments"][record["id"]] = record
    return record["id"]


def _get_experiment_record(session_id: str, experiment_id: str) -> dict:
    session = _get_record(session_id)
    experiment = session["experiments"].get(experiment_id)
    if experiment is None:
        raise KeyError("Conjunto no encontrado (¿se eliminó o la sesión expiró?).")
    return experiment


def list_experiments(session_id: str) -> list[dict]:
    session = _get_record(session_id)
    return [
        {
            "id": e["id"],
            "name": e["name"],
            "kind": e["kind"],
            "sample_filter": e["sample_filter"].model_dump() if e["sample_filter"] else None,
            "is_mapped": e["mapping"] is not None,
        }
        for e in session["experiments"].values()
    ]


def get_experiment_summary(session_id: str, experiment_id: str) -> dict:
    e = _get_experiment_record(session_id, experiment_id)
    return {
        "id": e["id"],
        "name": e["name"],
        "kind": e["kind"],
        "sample_filter": e["sample_filter"].model_dump() if e["sample_filter"] else None,
        "is_mapped": e["mapping"] is not None,
    }


def rename_experiment(session_id: str, experiment_id: str, name: str) -> None:
    _get_experiment_record(session_id, experiment_id)["name"] = name


def set_experiment_filter(session_id: str, experiment_id: str, sample_filter: SampleFilter | None) -> None:
    experiment = _get_experiment_record(session_id, experiment_id)
    experiment["sample_filter"] = sample_filter
    # Cambiar el filtro invalida cualquier mapeo ya aplicado sobre la submuestra anterior.
    experiment["mapping"] = None
    experiment["long_df"] = None


def duplicate_experiment(session_id: str, experiment_id: str, new_name: str) -> str:
    source = _get_experiment_record(session_id, experiment_id)
    session = _get_record(session_id)
    record = _new_experiment_record(new_name, source["kind"], source["sample_filter"])
    record["mapping"] = source["mapping"]
    record["long_df"] = source["long_df"].copy() if source["long_df"] is not None else None
    session["experiments"][record["id"]] = record
    return record["id"]


def delete_experiment(session_id: str, experiment_id: str) -> None:
    session = _get_record(session_id)
    session["experiments"].pop(experiment_id, None)


def get_experiment_kind(session_id: str, experiment_id: str) -> str:
    return _get_experiment_record(session_id, experiment_id)["kind"]


def get_experiment_filter(session_id: str, experiment_id: str) -> SampleFilter | None:
    return _get_experiment_record(session_id, experiment_id)["sample_filter"]


def get_filtered_df(session_id: str, experiment_id: str) -> pd.DataFrame:
    """El dataframe original recortado por el filtro de submuestra del
    conjunto (p. ej. `EXPERIMENTO == 1`), si tiene uno definido."""
    df = get_df(session_id)
    sample_filter = get_experiment_filter(session_id, experiment_id)
    if sample_filter is None or sample_filter.column not in df.columns:
        return df
    mask = df[sample_filter.column].astype(str).isin(sample_filter.values)
    return df[mask]


def set_experiment_mapping(
    session_id: str, experiment_id: str, mapping: ConjointMappingConfig | VignetteMappingConfig, long_df: pd.DataFrame
) -> None:
    experiment = _get_experiment_record(session_id, experiment_id)
    experiment["mapping"] = mapping
    experiment["long_df"] = long_df


def get_experiment_mapping(session_id: str, experiment_id: str) -> ConjointMappingConfig | VignetteMappingConfig | None:
    return _get_experiment_record(session_id, experiment_id)["mapping"]


def get_experiment_long_df(session_id: str, experiment_id: str) -> pd.DataFrame | None:
    return _get_experiment_record(session_id, experiment_id)["long_df"]
