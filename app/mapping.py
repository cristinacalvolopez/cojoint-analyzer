"""Detección automática y validación del mapeo wide -> long del conjoint.

La base viene en formato ancho con nombres de columna que casi siempre
siguen un patrón regular tipo ``<tarea>_<perfil>_<atributo>`` (p. ej.
``cj1_A_gen``, ``cj3_B_ca_1``) y una columna de elección por tarea (p. ej.
``cj1_eleccion`` o ``cj1_elige``). `suggest_mapping` intenta reconocer ese
patrón para proponer una configuración inicial; el usuario la revisa y
corrige en la interfaz antes de reestructurar los datos, así que el
detector puede permitirse ser conservador y dejar columnas sin asignar en
vez de adivinar mal.
"""
import re
from collections import defaultdict

import pandas as pd

from .schema import AttributeMapping, ConjointMappingConfig

# <tarea>_<perfil>_<atributo>, p. ej. cj1_A_gen, cj3_B_ca_1
_TASK_PROFILE_ATTR_RE = re.compile(
    r"^(?P<task>[A-Za-z]+\d+)_(?P<profile>[A-Za-z]{1,3})_(?P<attr>.+)$"
)

# columna de elección de una tarea, p. ej. cj1_eleccion, cj1_elige, cj1_choice
_CHOICE_RE = re.compile(
    r"^(?P<task>[A-Za-z]+\d+)_(?:eleccion|elige|elegido|choice|winner|pref\w*)$",
    re.IGNORECASE,
)

_ID_CANDIDATES = ("id", "id_encuesta", "caseid", "case_id", "respondent", "respondent_id", "folio", "idnum")


def _looks_like_profile_token(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z]{1,3}", token))


def suggest_mapping(columns: list[str]) -> dict:
    """Propone una configuración inicial a partir de los nombres de columna.

    Devuelve un dict serializable (no `ConjointMappingConfig` directamente)
    con la config sugerida más la lista de columnas que no se pudieron
    clasificar, para que la interfaz las muestre y el usuario decida.
    """
    tasks: set[str] = set()
    profiles: set[str] = set()
    attr_columns: dict[str, dict[str, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
    choice_columns: dict[str, str] = {}
    matched: set[str] = set()

    for col in columns:
        m = _CHOICE_RE.match(col)
        if m:
            task = m.group("task")
            choice_columns[task] = col
            tasks.add(task)
            matched.add(col)

    for col in columns:
        if col in matched:
            continue
        m = _TASK_PROFILE_ATTR_RE.match(col)
        if not m:
            continue
        task, profile, attr = m.group("task"), m.group("profile"), m.group("attr")
        if not _looks_like_profile_token(profile):
            continue
        tasks.add(task)
        profiles.add(profile)
        attr_columns[attr][task][profile] = col
        matched.add(col)

    unmatched = [c for c in columns if c not in matched]

    def _task_sort_key(t: str):
        digits = re.search(r"\d+", t)
        return (t[: digits.start()] if digits else t, int(digits.group()) if digits else 0)

    ordered_tasks = sorted(tasks, key=_task_sort_key)
    ordered_profiles = sorted(profiles)

    attributes = [
        {
            "name": attr,
            "label": attr,
            "columns": {task: dict(profile_map) for task, profile_map in per_task.items()},
        }
        for attr, per_task in attr_columns.items()
    ]

    respondent_id = next((c for c in columns if c.lower() in _ID_CANDIDATES), None)

    return {
        "respondent_id": respondent_id,
        "tasks": ordered_tasks,
        "profiles": ordered_profiles,
        "attributes": attributes,
        "choice_columns": choice_columns,
        "choice_value_map": {p: p for p in ordered_profiles},
        "unmatched_columns": unmatched,
    }


def validate_config(df: pd.DataFrame, config: ConjointMappingConfig) -> list[str]:
    """Devuelve una lista de problemas (cadenas legibles). Lista vacía = ok.

    No lanza excepción: la interfaz muestra los avisos y deja decidir al
    usuario si son bloqueantes (p. ej. un atributo sin columna en una tarea
    concreta puede ser intencional si esa tarea no usa ese atributo).
    """
    issues: list[str] = []

    if config.respondent_id is not None and config.respondent_id not in df.columns:
        issues.append(f'La columna de identificador "{config.respondent_id}" no existe en el fichero.')

    if config.respondent_id is not None and df[config.respondent_id].duplicated().any():
        issues.append(
            f'La columna de identificador "{config.respondent_id}" tiene valores repetidos: '
            "revisa que sea un identificador único por entrevistado."
        )

    for task in config.tasks:
        choice_col = config.choice_columns.get(task)
        if not choice_col:
            issues.append(f'La tarea "{task}" no tiene columna de elección asignada.')
        elif choice_col not in df.columns:
            issues.append(f'La columna de elección "{choice_col}" de la tarea "{task}" no existe en el fichero.')
        else:
            observed = set(df[choice_col].dropna().astype(str).unique())
            unmapped = observed - set(config.choice_value_map.keys())
            if unmapped:
                issues.append(
                    f'La columna de elección de la tarea "{task}" tiene valores sin traducir a perfil: '
                    f"{', '.join(sorted(unmapped))}."
                )

        for profile in config.profiles:
            for attr in config.attributes:
                col = attr.columns.get(task, {}).get(profile)
                if not col:
                    issues.append(f'Falta columna para el atributo "{attr.name}", tarea "{task}", perfil "{profile}".')
                elif col not in df.columns:
                    issues.append(f'La columna "{col}" (atributo "{attr.name}", tarea "{task}", perfil "{profile}") no existe.')

    return issues
