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

# Columna de elección de una tarea, p. ej. cj1_eleccion, cj1_elige, cj1_choice.
# En orden de prioridad: algunos cuestionarios tienen más de una columna que
# casa con el patrón para la misma tarea (p. ej. "cj1_elige" como metadato de
# diseño -qué perfil era la referencia- y "cj1_eleccion" con la letra elegida
# de verdad). Cuando hay ambigüedad preferimos el término inequívoco
# "elección" al abreviado "elige", que en la práctica ha resultado ser menos
# fiable como nombre de la variable de respuesta real.
_CHOICE_TOKEN_PATTERNS = [
    re.compile(r"^(?P<task>[A-Za-z]+\d+)_eleccion$", re.IGNORECASE),
    re.compile(r"^(?P<task>[A-Za-z]+\d+)_elegido$", re.IGNORECASE),
    re.compile(r"^(?P<task>[A-Za-z]+\d+)_choice$", re.IGNORECASE),
    re.compile(r"^(?P<task>[A-Za-z]+\d+)_winner$", re.IGNORECASE),
    re.compile(r"^(?P<task>[A-Za-z]+\d+)_seleccion$", re.IGNORECASE),
    re.compile(r"^(?P<task>[A-Za-z]+\d+)_elige$", re.IGNORECASE),
    re.compile(r"^(?P<task>[A-Za-z]+\d+)_pref\w*$", re.IGNORECASE),
]

_ID_CANDIDATES = ("id", "id_encuesta", "caseid", "case_id", "respondent", "respondent_id", "folio", "idnum")

# Valores de "no respuesta" habituales en columnas de elección: no cuentan
# como perfil sin traducir, así que no deben forzar al detector posicional a
# incluirlos como si fueran un perfil más.
_MISSING_VALUE_TOKENS = {
    "ns/nc", "ns", "nc", "no sabe", "no contesta", "no sabe/no contesta",
    "no sabe / no contesta", "nan", "none", "",
}


def _looks_like_profile_token(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z]{1,3}", token))


def _task_sort_key(t: str):
    digits = re.search(r"\d+", t)
    return (t[: digits.start()] if digits else t, int(digits.group()) if digits else 0)


_TASK_TOKEN_RE = re.compile(r"^([A-Za-z]+\d+)_")


def candidate_tasks(columns: list[str]) -> list[str]:
    """Todas las tareas que aparecen como prefijo `<tarea>_` en algún nombre de
    columna, aunque esa columna en concreto no haya podido clasificarse como
    atributo o elección. Sirve para poblar el selector de "añadir tarea" en la
    interfaz: nunca hay que escribir el nombre de una tarea a mano, se elige
    de esta lista.
    """
    found: set[str] = set()
    for col in columns:
        m = _TASK_TOKEN_RE.match(col)
        if m:
            found.add(m.group(1))
    return sorted(found, key=_task_sort_key)


def candidate_profiles(columns: list[str]) -> list[str]:
    """Todos los tokens de perfil que aparecen en el patrón
    `<tarea>_<perfil>_<atributo>` en cualquier columna del fichero, para
    poblar el selector de "añadir perfil" sin caja de texto libre.
    """
    found: set[str] = set()
    for col in columns:
        m = _TASK_PROFILE_ATTR_RE.match(col)
        if m and _looks_like_profile_token(m.group("profile")):
            found.add(m.group("profile"))
    return sorted(found)


def _looks_like_missing_value(value: str) -> bool:
    return value.strip().casefold() in _MISSING_VALUE_TOKENS


def infer_choice_value_map(
    df: pd.DataFrame, choice_columns: dict[str, str], profiles: list[str]
) -> tuple[dict[str, str], list[str]]:
    """Deduce a qué perfil corresponde cada valor observado en las columnas de
    elección, en vez de asumir que el valor crudo coincide literalmente con el
    id de perfil (p. ej. que la columna valga exactamente "A"/"B").

    En la práctica el valor observado casi nunca es el id de perfil pelado:
    Stata/SPSS convierten el código a su etiqueta de valor ("Perfil A",
    "Candidato/a 1"...), así que probamos, en orden de fiabilidad decreciente:

    1. Coincidencia exacta (insensible a mayúsculas) con el id de perfil.
    2. El id de perfil aparece como token suelto dentro del valor observado
       (p. ej. perfil "A" dentro de "Perfil A"), y de forma no ambigua.
    3. Correspondencia posicional por el número final del valor observado
       (p. ej. "Candidato/a 1"/"Candidato/a 2" con perfiles ["A", "B"]),
       solo cuando sobran tantos valores numerables como perfiles quedan
       por asignar.

    Devuelve `(choice_value_map, valores_sin_traducir)`; el segundo elemento
    son los valores observados que no se pudieron emparejar con ningún
    perfil (p. ej. "NS/NC"), útil para que la interfaz los muestre.
    """
    observed: set[str] = set()
    for col in choice_columns.values():
        if col in df.columns:
            observed |= set(df[col].dropna().astype(str).unique().tolist())

    value_map: dict[str, str] = {}

    # 1) coincidencia exacta insensible a mayúsculas
    for p in profiles:
        if p in value_map.values():
            continue
        for v in observed:
            if v in value_map:
                continue
            if v.strip().casefold() == p.strip().casefold():
                value_map[v] = p
                break

    # 2) el id de perfil aparece como token suelto y sin ambigüedad
    remaining_profiles = [p for p in profiles if p not in value_map.values()]
    for p in remaining_profiles:
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(p)}(?![A-Za-z0-9])", re.IGNORECASE)
        candidates = [v for v in observed if v not in value_map and pattern.search(v)]
        if len(candidates) == 1:
            value_map[candidates[0]] = p

    # 3) correspondencia posicional por el número final del valor observado
    remaining_profiles = [p for p in profiles if p not in value_map.values()]
    if remaining_profiles:
        numbered = []
        for v in observed:
            if v in value_map or _looks_like_missing_value(v):
                continue
            m = re.search(r"(\d+)\s*$", v.strip())
            if m:
                numbered.append((int(m.group(1)), v))
        if len(numbered) >= len(remaining_profiles):
            numbered.sort(key=lambda t: t[0])
            for p, (_, v) in zip(remaining_profiles, numbered[: len(remaining_profiles)]):
                value_map[v] = p

    unmapped = sorted(v for v in observed if v not in value_map and not _looks_like_missing_value(v))
    return value_map, unmapped


def suggest_mapping(columns: list[str], df: pd.DataFrame | None = None) -> dict:
    """Propone una configuración inicial a partir de los nombres de columna.

    Si se pasa `df`, además deduce el `choice_value_map` a partir de los
    valores realmente observados en las columnas de elección (ver
    `infer_choice_value_map`) en vez de asumir que valen literalmente el id
    de perfil; sin `df` se mantiene el comportamiento anterior (identidad
    perfil -> perfil) para quien solo tenga los nombres de columna.

    Devuelve un dict serializable (no `ConjointMappingConfig` directamente)
    con la config sugerida más la lista de columnas que no se pudieron
    clasificar, para que la interfaz las muestre y el usuario decida.
    """
    tasks: set[str] = set()
    profiles: set[str] = set()
    attr_columns: dict[str, dict[str, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
    choice_columns: dict[str, str] = {}
    matched: set[str] = set()

    for pattern in _CHOICE_TOKEN_PATTERNS:
        for col in columns:
            m = pattern.match(col)
            if not m:
                continue
            task = m.group("task")
            if task not in choice_columns:
                choice_columns[task] = col
                tasks.add(task)
            matched.add(col)  # también las columnas de menor prioridad descartadas para esa tarea

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

    if df is not None and choice_columns:
        choice_value_map, unmatched_choice_values = infer_choice_value_map(df, choice_columns, ordered_profiles)
    else:
        choice_value_map, unmatched_choice_values = {p: p for p in ordered_profiles}, []

    return {
        "respondent_id": respondent_id,
        "tasks": ordered_tasks,
        "profiles": ordered_profiles,
        "attributes": attributes,
        "choice_columns": choice_columns,
        "choice_value_map": choice_value_map,
        "unmatched_choice_values": unmatched_choice_values,
        "unmatched_columns": unmatched,
        "candidate_tasks": candidate_tasks(columns),
        "candidate_profiles": candidate_profiles(columns),
    }


def classify_unmapped_choice_values(df: pd.DataFrame, config: ConjointMappingConfig) -> dict[str, list[str]]:
    """Separa, entre todos los valores observados en las columnas de elección
    que no están en `choice_value_map`, los que parecen no-respuesta (NS/NC…)
    de los que no se reconocen como tales. Se usa para que el resumen de la
    reestructuración explique *por qué* hay conjuntos de elección sin perfil
    elegido, en vez de mostrar solo un recuento que parece siempre un error.
    """
    observed: set[str] = set()
    for task in config.tasks:
        choice_col = config.choice_columns.get(task)
        if choice_col and choice_col in df.columns:
            observed |= set(df[choice_col].dropna().astype(str).unique())
    unmapped = observed - set(config.choice_value_map.keys())
    return {
        "missing_like": sorted(v for v in unmapped if _looks_like_missing_value(v)),
        "unrecognized": sorted(v for v in unmapped if not _looks_like_missing_value(v)),
    }


def validate_config(df: pd.DataFrame, config: ConjointMappingConfig) -> list[dict]:
    """Devuelve una lista de problemas: `{"text": ..., "severity": "warning"|"info"}`.
    Lista vacía = ok.

    No lanza excepción: la interfaz muestra los avisos y deja decidir al
    usuario si son bloqueantes (p. ej. un atributo sin columna en una tarea
    concreta puede ser intencional si esa tarea no usa ese atributo). La
    severidad "info" es para lo que es normal en cualquier encuesta (no
    respuesta) y no necesita corregirse, a diferencia de "warning".
    """
    issues: list[dict] = []

    def warn(text: str) -> None:
        issues.append({"text": text, "severity": "warning"})

    def info(text: str) -> None:
        issues.append({"text": text, "severity": "info"})

    if config.respondent_id is not None and config.respondent_id not in df.columns:
        warn(f'La columna de identificador "{config.respondent_id}" no existe en el fichero.')

    if config.respondent_id is not None and df[config.respondent_id].duplicated().any():
        warn(
            f'La columna de identificador "{config.respondent_id}" tiene valores repetidos: '
            "revisa que sea un identificador único por entrevistado."
        )

    for task in config.tasks:
        choice_col = config.choice_columns.get(task)
        if not choice_col:
            warn(f'La tarea "{task}" no tiene columna de elección asignada.')
        elif choice_col not in df.columns:
            warn(f'La columna de elección "{choice_col}" de la tarea "{task}" no existe en el fichero.')
        else:
            observed = set(df[choice_col].dropna().astype(str).unique())
            unmapped = observed - set(config.choice_value_map.keys())
            missing_like = sorted(v for v in unmapped if _looks_like_missing_value(v))
            unrecognized = sorted(v for v in unmapped if not _looks_like_missing_value(v))
            if missing_like:
                info(
                    f'La tarea "{task}" tiene códigos de no respuesta en la columna de elección '
                    f"({', '.join(missing_like)}): esas filas se tratarán como sin elección, es normal "
                    "si la encuesta permite no contestar."
                )
            if unrecognized:
                warn(
                    f'La columna de elección de la tarea "{task}" tiene valores sin traducir a ningún perfil: '
                    f"{', '.join(unrecognized)}. Si no son de no respuesta, revisa si falta añadirlos al mapeo."
                )

        for profile in config.profiles:
            for attr in config.attributes:
                col = attr.columns.get(task, {}).get(profile)
                if not col:
                    warn(f'Falta columna para el atributo "{attr.name}", tarea "{task}", perfil "{profile}".')
                elif col not in df.columns:
                    warn(f'La columna "{col}" (atributo "{attr.name}", tarea "{task}", perfil "{profile}") no existe.')

    return issues
