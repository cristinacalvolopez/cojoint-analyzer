"""Tablas descriptivas para conjuntos de tipo "viñeta": comparar cómo
cambian varias variables de resultado según el atributo del estímulo que le
tocó a cada entrevistado (p. ej. la gravedad percibida, la justicia de la
sentencia, la pena de prisión considerada adecuada... todas por "Texto A" vs
"Texto B"), en vez de tener que elegir una única variable dependiente y
correr una regresión por cada una.

También cubre "conjuntos de respuesta múltiple": preguntas donde el
entrevistado puede marcar varias opciones a la vez, cada una guardada en su
propia columna binaria/casi-binaria (p. ej. "¿cuáles crees que son los
motivos...?" con una columna por motivo, no vacía si se marcó ese motivo).
"""
import pandas as pd

from .vignette import coerce_scale_numeric


def build_crosstab(
    df: pd.DataFrame,
    outcome_column: str,
    outcome_label: str,
    group_column: str,
    group_label: str,
) -> dict:
    """Tabla cruzada de `outcome_column` (filas) por `group_column` (columnas):
    recuento y porcentaje de columna, más un resumen numérico (media,
    mediana, desviación típica) si `outcome_column` se puede tratar como
    escala. Las filas de resultado se ordenan numéricamente si son un código
    de escala (0, 1, 2…) y, si no, por el orden en que aparecen en los datos.
    """
    sub = df[[outcome_column, group_column]].copy()
    sub = sub.dropna(subset=[group_column])
    sub[outcome_column] = sub[outcome_column].astype(object)
    sub = sub.dropna(subset=[outcome_column])

    if sub.empty:
        return {
            "outcome_column": outcome_column,
            "outcome_label": outcome_label,
            "group_column": group_column,
            "group_label": group_label,
            "group_levels": [],
            "row_levels": [],
            "counts": {},
            "percentages": {},
            "column_totals": {},
            "numeric_summary": None,
            "n": 0,
        }

    outcome_str = sub[outcome_column].astype(str)
    group_str = sub[group_column].astype(str)

    counts = pd.crosstab(outcome_str, group_str)
    column_totals = counts.sum(axis=0)
    percentages = counts.div(column_totals, axis=1) * 100

    group_levels = sorted(counts.columns.tolist())
    numeric_outcome = coerce_scale_numeric(sub[outcome_column])
    is_numeric = numeric_outcome.notna().sum() == len(sub)
    if is_numeric:
        # Ordenar por el valor ya coaccionado, no por el texto crudo ("10 Muy
        # grave" no es un `float` válido, aunque represente el nivel 10).
        numeric_by_label = dict(zip(outcome_str, numeric_outcome))
        row_levels = sorted(counts.index.tolist(), key=lambda v: numeric_by_label[v])
    else:
        row_levels = counts.index.tolist()

    numeric_summary = None
    if is_numeric:
        numeric_summary = {}
        overall = numeric_outcome
        for level in group_levels:
            values = numeric_outcome[group_str == level]
            numeric_summary[level] = {
                "n": int(values.notna().sum()),
                "mean": float(values.mean()) if len(values) else None,
                "median": float(values.median()) if len(values) else None,
                "sd": float(values.std()) if len(values) > 1 else None,
            }
        numeric_summary["__total__"] = {
            "n": int(overall.notna().sum()),
            "mean": float(overall.mean()) if len(overall) else None,
            "median": float(overall.median()) if len(overall) else None,
            "sd": float(overall.std()) if len(overall) > 1 else None,
        }

    return {
        "outcome_column": outcome_column,
        "outcome_label": outcome_label,
        "group_column": group_column,
        "group_label": group_label,
        "group_levels": group_levels,
        "row_levels": row_levels,
        "counts": {row: {col: int(counts.loc[row, col]) for col in group_levels} for row in row_levels},
        "percentages": {
            row: {col: float(percentages.loc[row, col]) for col in group_levels} for row in row_levels
        },
        "column_totals": {col: int(column_totals[col]) for col in group_levels},
        "numeric_summary": numeric_summary,
        "n": int(len(sub)),
    }


def build_multi_response_summary(
    df: pd.DataFrame,
    items: list[dict],
    group_column: str | None = None,
    group_label: str | None = None,
) -> dict:
    """Resumen de un conjunto de respuesta múltiple: para cada opción
    (`items`, cada una `{"column", "label", "selected_value"}`), el
    recuento y "% de casos" (base = entrevistados con al menos una
    respuesta no perdida en el conjunto), y desglosado por `group_column`
    si se indica.

    `selected_value`: si se da, cuenta como "marcada" solo cuando la
    columna vale exactamente ese texto; si es `None`, cualquier valor no
    nulo cuenta como marcada (el patrón habitual de estos ficheros: nulo =
    no se marcó esa opción).
    """
    columns = [it["column"] for it in items]
    present_cols = [c for c in columns if c in df.columns]

    selected_masks = {}
    for it in items:
        col = it["column"]
        if col not in df.columns:
            continue
        series = df[col]
        if it.get("selected_value") is not None:
            selected_masks[col] = series.astype(str) == str(it["selected_value"])
        else:
            selected_masks[col] = series.notna()

    any_selected = pd.Series(False, index=df.index)
    for mask in selected_masks.values():
        any_selected = any_selected | mask
    valid_base = df[present_cols].notna().any(axis=1) if present_cols else any_selected
    base_n = int(valid_base.sum())

    def _summary_for(mask_source: pd.Series) -> dict:
        base = int(mask_source.sum())
        rows = []
        for it in items:
            col = it["column"]
            mask = selected_masks.get(col)
            n = int((mask & mask_source).sum()) if mask is not None else 0
            rows.append({
                "column": col,
                "label": it.get("label") or col,
                "n": n,
                "pct_of_cases": (n / base * 100) if base else None,
            })
        rows.sort(key=lambda r: r["n"], reverse=True)
        return {"base_n": base, "rows": rows}

    result = {
        "base_n": base_n,
        "overall": _summary_for(valid_base)["rows"],
        "by_group": None,
        "group_column": group_column,
        "group_label": group_label,
    }

    if group_column and group_column in df.columns:
        by_group = {}
        for level in sorted(df[group_column].dropna().astype(str).unique()):
            level_mask = valid_base & (df[group_column].astype(str) == level)
            by_group[level] = _summary_for(level_mask)
        result["by_group"] = by_group

    return result
