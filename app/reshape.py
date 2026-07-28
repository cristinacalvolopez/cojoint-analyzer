"""Motor de transformación wide -> long para el experimento conjoint.

Cada fila del fichero ancho (un entrevistado) se despliega en
``n_tareas * n_perfiles`` filas del fichero largo: una fila por perfil
evaluado, con sus atributos, la tarea y el perfil a los que pertenece, el
identificador del conjunto de elección (necesario para el clogit) y la
variable binaria `chosen` que indica si ese perfil fue el elegido en esa
tarea.
"""
import numpy as np
import pandas as pd

from .schema import ConjointMappingConfig


def wide_to_long(df: pd.DataFrame, config: ConjointMappingConfig) -> pd.DataFrame:
    if config.respondent_id is not None:
        respondent = df[config.respondent_id]
    else:
        respondent = pd.Series(df.index, index=df.index, name="respondent_id")
    respondent = respondent.astype(str)

    blocks: list[pd.DataFrame] = []
    for task in config.tasks:
        choice_col = config.choice_columns.get(task)
        raw_choice = df[choice_col].astype(str) if choice_col in (df.columns if choice_col else []) else None
        chosen_profile = raw_choice.map(config.choice_value_map) if raw_choice is not None else None

        for profile in config.profiles:
            block = pd.DataFrame(index=df.index)
            block["respondent_id"] = respondent
            block["task"] = task
            block["profile"] = profile
            block["choice_set"] = respondent + "__" + str(task)

            for attr in config.attributes:
                col = attr.columns.get(task, {}).get(profile)
                block[attr.name] = df[col] if col in df.columns else np.nan

            if chosen_profile is not None:
                block["chosen"] = (chosen_profile == profile).astype("Int64")
                block.loc[chosen_profile.isna(), "chosen"] = pd.NA
            else:
                block["chosen"] = pd.NA

            blocks.append(block)

    long_df = pd.concat(blocks, ignore_index=True)
    long_df = long_df.sort_values(["respondent_id", "task", "profile"]).reset_index(drop=True)
    return long_df


def reshape_summary(long_df: pd.DataFrame, config: ConjointMappingConfig) -> dict:
    n_respondents = long_df["respondent_id"].nunique()
    n_choice_sets = long_df["choice_set"].nunique()
    n_rows = len(long_df)
    missing_choice = int(long_df["chosen"].isna().sum())

    # Cada conjunto de elección (entrevistado x tarea) debe tener exactamente
    # un perfil marcado como elegido; si no, algo falló en el mapeo de la
    # columna de elección (valor sin traducir, no-respuesta, etc.).
    choice_counts = long_df.groupby("choice_set")["chosen"].sum(min_count=1)
    sets_without_choice = int((choice_counts.fillna(0) == 0).sum())
    sets_with_multiple = int((choice_counts.fillna(0) > 1).sum())

    attribute_coverage = {
        attr: {
            "n_missing": int(long_df[attr].isna().sum()),
            "n_levels": int(long_df[attr].dropna().astype(str).nunique()),
            "levels": sorted(long_df[attr].dropna().astype(str).unique().tolist()),
        }
        for attr in config.attribute_names()
    }

    return {
        "n_respondents": n_respondents,
        "n_tasks": len(config.tasks),
        "n_profiles": len(config.profiles),
        "n_choice_sets": n_choice_sets,
        "n_rows": n_rows,
        "missing_choice_rows": missing_choice,
        "choice_sets_without_selection": sets_without_choice,
        "choice_sets_with_multiple_selections": sets_with_multiple,
        "attribute_coverage": attribute_coverage,
    }
