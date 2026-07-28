"""Almacén en memoria de los datasets subidos y de su configuración de
análisis conjoint, indexados por sesión.

No hay persistencia en disco ni base de datos: los datos viven solo mientras
el proceso está en marcha, lo cual es deliberado dado que la base contiene
datos de entrevistas sobre actitudes hacia la comunidad LGTBIQ+.
"""
import time
import uuid

import pandas as pd

from .schema import ConjointMappingConfig

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
        "mapping": None,
        "long_df": None,
    }
    return session_id


def get_df(session_id: str) -> pd.DataFrame:
    return _get_record(session_id)["df"]


def get_labels(session_id: str) -> dict[str, str]:
    return _get_record(session_id)["labels"]


def delete_session(session_id: str) -> None:
    _SESSIONS.pop(session_id, None)


def set_mapping(session_id: str, mapping: ConjointMappingConfig, long_df: pd.DataFrame) -> None:
    session = _get_record(session_id)
    session["mapping"] = mapping
    session["long_df"] = long_df


def get_mapping(session_id: str) -> ConjointMappingConfig | None:
    return _get_record(session_id)["mapping"]


def get_long_df(session_id: str) -> pd.DataFrame | None:
    return _get_record(session_id)["long_df"]
