"""Conjoint de elección cuyo diseño vive en un fichero aparte.

Algunos experimentos de elección no incrustan los atributos de cada perfil
como columnas del fichero de respuestas: solo guardan qué perfil ganó cada
tarea (p. ej. "Candidato/a 1" vs "Candidato/a 2") y un código de versión
aleatoria asignada al entrevistado. Los atributos reales que vio cada
perfil en cada tarea viven en un fichero de diseño/plan de bloques aparte
(el que generó la herramienta de aleatorización), indexado por versión,
tarea y perfil — y a veces también por una variable de bloque adicional
(p. ej. la comunidad autónoma, si el diseño reparte bloques por región).

Este módulo cruza ambos ficheros y produce un fichero largo con la misma
forma que `reshape.wide_to_long()` (`respondent_id`, `task`, `profile`,
`choice_set`, `chosen`, más una columna por atributo), así que
`amce.run_amce`/`run_clogit_amce` y `reshape.reshape_summary` funcionan
sin cambios sobre el resultado.
"""
import re

import numpy as np
import pandas as pd

from .mapping import looks_like_missing_value
from .schema import ExternalDesignMappingConfig

_CATCH_ALL_HINTS = ("resto", "otra", "otro", "other", "rest", "demás", "demas")
_TRAILING_NUMBER_RE = re.compile(r"(\d+)\s*$")


def suggest_task_profile_columns(design_df: pd.DataFrame) -> dict:
    """Heurística ligera para adivinar qué columna del diseño es la tarea/
    pantalla y cuál el perfil/posición: nombres habituales primero, si no,
    la columna con menos niveles distintos suele ser el perfil (2-4) y la
    siguiente con más la tarea (5-20). Es solo una sugerencia editable.
    """
    task_name_hints = ("set", "tarea", "screen", "pantalla", "task", "escenario")
    profile_name_hints = ("posicion", "posición", "perfil", "profile", "position", "candidato")

    task_col = next((c for c in design_df.columns if c.lower() in task_name_hints), None)
    profile_col = next((c for c in design_df.columns if c.lower() in profile_name_hints), None)

    if task_col is None or profile_col is None:
        numeric_cols = [c for c in design_df.columns if pd.api.types.is_numeric_dtype(design_df[c])]
        by_cardinality = sorted(numeric_cols, key=lambda c: design_df[c].nunique())
        if profile_col is None:
            candidates = [c for c in by_cardinality if c != task_col and 2 <= design_df[c].nunique() <= 4]
            profile_col = candidates[0] if candidates else None
        if task_col is None:
            candidates = [c for c in by_cardinality if c != profile_col and 2 <= design_df[c].nunique() <= 50]
            task_col = candidates[-1] if candidates else None

    return {"design_task_column": task_col, "design_profile_column": profile_col}


def suggest_remaining_columns(design_df: pd.DataFrame, task_col: str | None, profile_col: str | None) -> list[str]:
    return [c for c in design_df.columns if c not in (task_col, profile_col)]


def suggest_join_key_columns(
    design_df: pd.DataFrame, respondent_df: pd.DataFrame, remaining_design_columns: list[str]
) -> list[str]:
    """De las columnas del diseño que no son tarea ni perfil, cuáles parecen
    una clave de cruce (variable de contexto, p. ej. la comunidad autónoma o
    la versión) en vez de un atributo del propio perfil: si el nombre
    coincide (insensible a mayúsculas) con una columna del fichero de
    respuestas, es un fuerte indicio de que hay que cruzarla, no tratarla
    como atributo del AMCE.
    """
    respondent_cols_lower = {c.lower(): c for c in respondent_df.columns}
    return [c for c in remaining_design_columns if c.lower() in respondent_cols_lower]


def suggest_respondent_column_for(design_column: str, respondent_df: pd.DataFrame) -> str | None:
    respondent_cols_lower = {c.lower(): c for c in respondent_df.columns}
    return respondent_cols_lower.get(design_column.lower())


def suggest_value_map(
    respondent_df: pd.DataFrame, respondent_column: str, design_values: list[str]
) -> tuple[dict[str, str], str | None]:
    """Para una clave de cruce, propone a qué valor del diseño corresponde
    cada valor observado en la columna del entrevistado, en orden de
    fiabilidad decreciente:

    1. Coincidencia exacta (insensible a mayúsculas), p. ej. "Galicia" ->
       "Galicia".
    2. El número final del valor observado coincide con un valor de diseño
       puramente numérico, p. ej. "Versión 19" -> "19" (habitual cuando SPSS
       convierte un código de versión a su etiqueta de texto).

    Si sobra exactamente un valor de diseño con pinta de "cajón de sastre"
    (contiene "resto", "otra"...), se propone como valor por defecto para lo
    que no case explícitamente — pero un valor que cae en el valor por
    defecto sin haber hecho *ninguna* coincidencia real (ni exacta ni por
    número) puede ser, en realidad, un caso como "Comunitat Valenciana" que
    debería mapear a "País Valencià" y no a "Resto CCAA": por eso conviene
    revisar la tabla completa, no fiarse solo de que no salte ningún aviso.
    """
    observed = sorted(respondent_df[respondent_column].dropna().astype(str).unique())
    design_by_lower = {v.strip().casefold(): v for v in design_values}
    design_by_number = {v.strip(): v for v in design_values if v.strip().lstrip("-").isdigit()}

    value_map: dict[str, str] = {}
    for v in observed:
        match = design_by_lower.get(v.strip().casefold())
        if not match:
            m = _TRAILING_NUMBER_RE.search(v.strip())
            if m:
                match = design_by_number.get(m.group(1))
        if match:
            value_map[v] = match

    catch_all_candidates = [v for v in design_values if any(h in v.casefold() for h in _CATCH_ALL_HINTS)]
    default_design_value = catch_all_candidates[0] if len(catch_all_candidates) == 1 else None

    return value_map, default_design_value


def suggest_choice_columns(respondent_df: pd.DataFrame, tasks: list[str]) -> dict[str, str]:
    """Para cada tarea (tal y como aparece en la columna de tarea del
    diseño, p. ej. "1".."10"), busca en el fichero de respuestas la columna
    correspondiente, asumiendo el patrón habitual de una columna por
    pantalla con un mismo prefijo y el número de tarea al final (p. ej.
    "EXP1_1".."EXP1_10").

    Agrupar solo por el número final no basta en un cuestionario real: casi
    cualquier fichero tiene decenas de columnas que terminan en "1", "2"...
    (p. ej. "P5_1", "P12#1"). Por eso se agrupan las columnas por su
    "familia" (incluyendo el separador antes del número: "EXP1_",
    "P12#"...) y se elige la única familia que cubre las tareas pedidas con
    exactamente una columna cada una — si ninguna o más de una familia
    encaja, no se propone nada para esas tareas y hay que elegirlas a mano.
    """
    task_strs = [str(t) for t in tasks]
    task_set = set(task_strs)

    families: dict[str, dict[str, str]] = {}
    for col in respondent_df.columns:
        m = _TRAILING_NUMBER_RE.search(col)
        if not m:
            continue
        stem = col[: m.start(1)]
        families.setdefault(stem, {})[m.group(1)] = col

    matching_stems = [stem for stem, mapping in families.items() if task_set.issubset(mapping.keys())]
    if len(matching_stems) != 1:
        return {}

    best = families[matching_stems[0]]
    return {t: best[t] for t in task_strs}


def validate_external_design_config(
    respondent_df: pd.DataFrame, design_df: pd.DataFrame, config: ExternalDesignMappingConfig
) -> list[dict]:
    """Devuelve `[{"text":..., "severity": "warning"|"info"}, ...]`. Lista
    vacía = ok. No lanza excepción: dejamos que la interfaz muestre los
    avisos y la usuaria decida.
    """
    issues: list[dict] = []

    def warn(text: str) -> None:
        issues.append({"text": text, "severity": "warning"})

    def info(text: str) -> None:
        issues.append({"text": text, "severity": "info"})

    if config.design_task_column not in design_df.columns:
        warn(f'La columna de tarea "{config.design_task_column}" no existe en el fichero de diseño.')
    if config.design_profile_column not in design_df.columns:
        warn(f'La columna de perfil "{config.design_profile_column}" no existe en el fichero de diseño.')

    for attr in config.attributes:
        if attr.design_column not in design_df.columns:
            warn(f'La columna "{attr.design_column}" del atributo "{attr.name}" no existe en el fichero de diseño.')

    for jk in config.join_keys:
        if jk.design_column not in design_df.columns:
            warn(f'La columna de cruce "{jk.design_column}" no existe en el fichero de diseño.')
        if jk.respondent_column not in respondent_df.columns:
            warn(f'La columna de cruce "{jk.respondent_column}" no existe en el fichero de respuestas.')
        elif jk.value_map:
            observed_series = respondent_df[jk.respondent_column].dropna().astype(str)
            observed = set(observed_series.unique())
            unmapped = observed - set(jk.value_map.keys())
            if jk.default_design_value:
                # Nada de lo no traducido se pierde (cae en el valor por defecto),
                # pero un valor que solo caiga ahí porque nunca se comprobó de
                # verdad (p. ej. "Comunitat Valenciana" cayendo en "Resto CCAA" en
                # vez de en "País Valencià") es un error silencioso: lo señalamos
                # como aviso informativo para que se revise la tabla, no porque
                # vaya a romper nada.
                defaulted = sorted(unmapped)
                n_defaulted = int(observed_series.isin(defaulted).sum())
                if defaulted:
                    info(
                        f'La clave de cruce "{jk.respondent_column}" asigna el valor por defecto '
                        f'"{jk.default_design_value}" a {n_defaulted} fila(s) con estos valores: '
                        f"{', '.join(defaulted)}. Revisa si alguno debería cruzar con otro valor del diseño "
                        "en vez de con el valor por defecto."
                    )
            elif unmapped:
                missing_like = sorted(v for v in unmapped if looks_like_missing_value(v))
                unrecognized = sorted(v for v in unmapped if not looks_like_missing_value(v))
                if unrecognized:
                    warn(
                        f'La clave de cruce "{jk.respondent_column}" tiene valores sin traducir y sin un valor '
                        f"por defecto: {', '.join(unrecognized)}. Esas filas no podrán cruzarse con el diseño."
                    )
                if missing_like:
                    info(f'La clave de cruce "{jk.respondent_column}" tiene valores de no respuesta: {", ".join(missing_like)}.')

    for task, choice_col in config.choice_columns.items():
        if choice_col not in respondent_df.columns:
            warn(f'La columna de elección "{choice_col}" de la tarea "{task}" no existe en el fichero de respuestas.')

    return issues


def _resolve_join_frame(respondent_df: pd.DataFrame, config: ExternalDesignMappingConfig) -> pd.DataFrame:
    join_df = pd.DataFrame(index=respondent_df.index)
    for jk in config.join_keys:
        if jk.respondent_column not in respondent_df.columns:
            join_df[jk.design_column] = np.nan
            continue
        raw = respondent_df[jk.respondent_column].astype(str)
        if jk.value_map:
            mapped = raw.map(jk.value_map)
            if jk.default_design_value is not None:
                mapped = mapped.fillna(jk.default_design_value)
        else:
            mapped = raw
        join_df[jk.design_column] = mapped
    return join_df


def build_long_df(
    respondent_df: pd.DataFrame, design_df: pd.DataFrame, config: ExternalDesignMappingConfig
) -> pd.DataFrame:
    if config.respondent_id is not None:
        respondent = respondent_df[config.respondent_id].astype(str)
    else:
        respondent = pd.Series(respondent_df.index.astype(str), index=respondent_df.index)

    join_df = _resolve_join_frame(respondent_df, config)
    join_cols = [jk.design_column for jk in config.join_keys]
    attr_cols = [a.design_column for a in config.attributes]
    task_col = config.design_task_column
    profile_col = config.design_profile_column

    blocks: list[pd.DataFrame] = []
    for task in config.tasks:
        choice_col = config.choice_columns.get(task)
        raw_choice = (
            respondent_df[choice_col].astype(str) if choice_col and choice_col in respondent_df.columns else None
        )
        chosen_profile = raw_choice.map(config.choice_value_map) if raw_choice is not None else None

        design_task_subset = design_df[design_df[task_col].astype(str) == str(task)]

        for profile in config.profiles:
            profile_rows = design_task_subset[design_task_subset[profile_col].astype(str) == str(profile)]

            block = pd.DataFrame(index=respondent_df.index)
            block["respondent_id"] = respondent
            block["task"] = str(task)
            block["profile"] = str(profile)
            block["choice_set"] = respondent + "__" + str(task)

            if join_cols:
                merge_left = join_df.copy()
                merge_left["_respondent_idx"] = respondent_df.index
                # El fichero de diseño casi siempre trae las claves de cruce como
                # número (int); el lado de las respuestas ya se ha convertido a
                # texto (por si hubo que traducir valores como "Versión 19" ->
                # "19"). Se homogeneiza a texto en ambos lados para poder cruzar.
                design_side = profile_rows[join_cols + attr_cols].copy()
                for col in join_cols:
                    design_side[col] = design_side[col].astype(str)
                merged = merge_left.merge(
                    design_side.drop_duplicates(subset=join_cols),
                    on=join_cols,
                    how="left",
                )
                merged = merged.set_index("_respondent_idx")
                for attr in config.attributes:
                    block[attr.name] = merged[attr.design_column]
            else:
                # Sin clave de cruce: el diseño no varía por entrevistado (una sola
                # combinación de atributos por tarea+perfil para todo el mundo).
                for attr in config.attributes:
                    value = profile_rows[attr.design_column].iloc[0] if not profile_rows.empty else np.nan
                    block[attr.name] = value

            if chosen_profile is not None:
                block["chosen"] = (chosen_profile == str(profile)).astype("Int64")
                block.loc[chosen_profile.isna(), "chosen"] = pd.NA
            else:
                block["chosen"] = pd.NA

            blocks.append(block)

    long_df = pd.concat(blocks, ignore_index=True)
    long_df = long_df.sort_values(["respondent_id", "task", "profile"]).reset_index(drop=True)
    return long_df
