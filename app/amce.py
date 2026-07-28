"""Estimación del Efecto Marginal Medio (AMCE) sobre el fichero largo.

Dos métodos, ambos estándar en la literatura de conjoint (Hainmueller,
Hopkins & Yamamoto 2014):

- ``ols``: regresión lineal de `chosen` (0/1) sobre variables dummy de cada
  atributo (una por nivel, salvo el nivel de referencia), con errores
  estándar agrupados (cluster-robust) por entrevistado, ya que cada persona
  responde a varias tareas y esas observaciones no son independientes.
- ``clogit``: logit condicional dentro de cada conjunto de elección
  (entrevistado x tarea), que explota directamente el diseño de elección
  forzada entre perfiles.

Los coeficientes de ambos métodos se devuelven en la misma forma (nivel,
atributo, referencia, estimación, error estándar, IC 95%, p-valor) para que
la capa de visualización no necesite distinguir el método usado.
"""
import re

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.discrete.conditional_models import ConditionalLogit


def _natural_sort_key(value: str):
    m = re.fullmatch(r"-?\d+(\.\d+)?", value)
    if m:
        return (0, float(value))
    return (1, value)


def category_levels(series: pd.Series) -> list[str]:
    values = series.dropna().astype(str).unique().tolist()
    return sorted(values, key=_natural_sort_key)


def build_design_matrix(
    df: pd.DataFrame, attributes: list[str], baselines: dict[str, str]
) -> tuple[pd.DataFrame, list[dict], dict[str, str]]:
    X = pd.DataFrame(index=df.index)
    meta: list[dict] = []
    baseline_map: dict[str, str] = {}

    for attr in attributes:
        series = df[attr].astype(str)
        levels = category_levels(series)
        if not levels:
            raise ValueError(f'El atributo "{attr}" no tiene valores no nulos en los datos.')

        requested = baselines.get(attr)
        baseline = requested if requested in levels else levels[0]
        baseline_map[attr] = baseline

        for level in levels:
            if level == baseline:
                continue
            col = f"{attr}[{level}]"
            X[col] = (series == level).astype(float)
            meta.append({"attribute": attr, "level": level, "baseline": baseline, "column": col})

    if X.shape[1] == 0:
        raise ValueError("No hay predictores válidos para el modelo (revisa los atributos elegidos).")
    return X, meta, baseline_map


def _prepare_data(long_df: pd.DataFrame, attributes: list[str]) -> pd.DataFrame:
    required = ["chosen", "choice_set", "respondent_id", *attributes]
    missing_cols = [c for c in required if c not in long_df.columns]
    if missing_cols:
        raise ValueError(f"Faltan columnas en el fichero largo: {', '.join(missing_cols)}.")
    sub = long_df.dropna(subset=["chosen", *attributes]).copy()
    if sub.empty:
        raise ValueError("No quedan filas completas (sin valores perdidos) para estimar el modelo.")
    return sub


def format_coefficients(
    params: pd.Series, bse: pd.Series, pvalues: pd.Series, conf_int: pd.DataFrame, meta: list[dict]
) -> list[dict]:
    meta_by_col = {m["column"]: m for m in meta}
    rows = []
    for name in params.index:
        entry = meta_by_col.get(name)
        if entry is None:
            continue  # término const u otro no perteneciente a un atributo mapeado
        rows.append(
            {
                "term": f'{entry["attribute"]}: {entry["level"]} (ref: {entry["baseline"]})',
                "attribute": entry["attribute"],
                "level": entry["level"],
                "baseline": entry["baseline"],
                "estimate": float(params[name]),
                "std_err": float(bse[name]),
                "ci_low": float(conf_int.loc[name, 0]),
                "ci_high": float(conf_int.loc[name, 1]),
                "p_value": float(pvalues[name]),
                "significant_at_05": bool(pvalues[name] < 0.05),
            }
        )
    return rows


def run_ols_amce(long_df: pd.DataFrame, attributes: list[str], baselines: dict[str, str] | None = None) -> dict:
    baselines = baselines or {}
    sub = _prepare_data(long_df, attributes)

    y = sub["chosen"].astype(float)
    X, meta, baseline_map = build_design_matrix(sub, attributes, baselines)
    X = sm.add_constant(X, has_constant="add")

    try:
        model = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": sub["respondent_id"]})
    except Exception as e:
        raise ValueError(f"No se pudo estimar el modelo OLS: {e}")

    conf_int = model.conf_int()
    return {
        "method": "ols",
        "n": int(model.nobs),
        "n_respondents": int(sub["respondent_id"].nunique()),
        "n_choice_sets": int(sub["choice_set"].nunique()),
        "r_squared": float(model.rsquared),
        "baselines": baseline_map,
        "coefficients": format_coefficients(model.params, model.bse, model.pvalues, conf_int, meta),
    }


def run_clogit_amce(long_df: pd.DataFrame, attributes: list[str], baselines: dict[str, str] | None = None) -> dict:
    baselines = baselines or {}
    sub = _prepare_data(long_df, attributes)

    # El logit condicional necesita, dentro de cada conjunto de elección,
    # variación en la variable dependiente (al menos un perfil elegido y al
    # menos uno no elegido); descartamos los conjuntos incompletos o sin
    # elección registrada.
    set_stats = sub.groupby("choice_set")["chosen"].agg(["sum", "count"])
    valid_sets = set_stats[(set_stats["sum"] >= 1) & (set_stats["sum"] < set_stats["count"])].index
    dropped = sub["choice_set"].nunique() - len(valid_sets)
    sub = sub[sub["choice_set"].isin(valid_sets)]
    if sub.empty:
        raise ValueError(
            "Ningún conjunto de elección tiene la variación necesaria (un perfil elegido y otro no) "
            "para estimar el logit condicional."
        )

    y = sub["chosen"].astype(float)
    X, meta, baseline_map = build_design_matrix(sub, attributes, baselines)

    try:
        model = ConditionalLogit(y, X, groups=sub["choice_set"]).fit(disp=0)
    except Exception as e:
        raise ValueError(f"No se pudo estimar el logit condicional: {e}")

    conf_int = model.conf_int()
    return {
        "method": "clogit",
        "n": int(sub.shape[0]),
        "n_respondents": int(sub["respondent_id"].nunique()),
        "n_choice_sets": int(len(valid_sets)),
        "choice_sets_dropped": int(dropped),
        "log_likelihood": float(model.llf),
        "baselines": baseline_map,
        "coefficients": format_coefficients(model.params, model.bse, model.pvalues, conf_int, meta),
    }


def run_amce(long_df: pd.DataFrame, method: str, attributes: list[str], baselines: dict[str, str] | None = None) -> dict:
    if method == "ols":
        return run_ols_amce(long_df, attributes, baselines)
    if method == "clogit":
        return run_clogit_amce(long_df, attributes, baselines)
    raise ValueError(f'Método no soportado: "{method}". Usa "ols" o "clogit".')


def to_plot_rows(result: dict) -> list[dict]:
    """Añade una fila de referencia (estimación 0, sin IC) por atributo para
    que el dot plot muestre también el nivel base, como es convención en
    los gráficos de AMCE publicados.
    """
    rows = []
    seen_attrs: set[str] = set()
    for coef in result["coefficients"]:
        attr = coef["attribute"]
        if attr not in seen_attrs:
            rows.append(
                {
                    "attribute": attr,
                    "level": coef["baseline"],
                    "is_baseline": True,
                    "estimate": 0.0,
                    "ci_low": None,
                    "ci_high": None,
                    "p_value": None,
                    "significant_at_05": False,
                }
            )
            seen_attrs.add(attr)
        rows.append(
            {
                "attribute": attr,
                "level": coef["level"],
                "is_baseline": False,
                "estimate": coef["estimate"],
                "ci_low": coef["ci_low"],
                "ci_high": coef["ci_high"],
                "p_value": coef["p_value"],
                "significant_at_05": coef["significant_at_05"],
            }
        )
    return rows
