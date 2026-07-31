"""Mapeo y estimación de experimentos de viñeta.

A diferencia del conjoint, en una viñeta cada entrevistado ve un único
perfil o estímulo (a menudo aleatorizado entre unas pocas versiones, p. ej.
"Texto A"/"Texto B") y lo valora en una variable de resultado continua o de
escala (p. ej. "¿hasta qué punto consideras grave esta agresión? 0-10"). No
hay perfiles enfrentados ni conjuntos de elección, así que no hace falta
reestructurar a formato largo: cada fila del fichero ancho ya es una
observación completa, y el análisis es una regresión OLS del resultado sobre
los niveles de cada atributo del estímulo.
"""
import re

import pandas as pd
import statsmodels.api as sm

from .amce import build_design_matrix, format_coefficients
from .schema import VignetteMappingConfig

# Sufijos habituales de metadatos que acompañan a una pregunta de escala
# (p. ej. "P2" con su "P2_NS" de "no sabe/no contesta" aparte) y no deben
# proponerse como variable de resultado en sí.
_SCALE_META_SUFFIX_RE = re.compile(r"(_ns|_dk|_noresponde)$", re.IGNORECASE)

# Mismos nombres típicos de identificador que `mapping._ID_CANDIDATES`: un ID
# de entrevistado es numérico y de recorrido tan amplio como el propio
# fichero, así que sin excluirlo por nombre colaría como "escala" en el
# heurístico de más abajo (nº de niveles no lo distingue: un ID también tiene
# muchos niveles, igual que una variable continua legítima).
_ID_CANDIDATES = (
    "id", "id_encuesta", "caseid", "case_id", "respondent", "respondent_id", "folio", "idnum",
    "numericalid", "key", "uuid", "guid",
)

# SPSS/Stata suelen poner etiqueta de texto solo en los extremos de una
# escala (p. ej. código 10 -> "10 Muy grave", código 0 -> "0 Nada grave") y
# dejar los valores intermedios como código puro. Una coerción numérica
# directa (`pd.to_numeric`) falla justo en esos extremos, que además suelen
# ser las respuestas más frecuentes (el "muy de acuerdo"/"nada grave" de
# cualquier escala). Por eso, para los valores que no se puedan convertir tal
# cual, reintentamos extrayendo el número inicial de la cadena.
_LEADING_NUMBER_RE = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)")


def coerce_scale_numeric(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    unresolved = numeric.isna() & series.notna()
    if unresolved.any():
        extracted = series[unresolved].astype(str).str.extract(_LEADING_NUMBER_RE, expand=False)
        extracted = extracted.str.replace(",", ".", regex=False)
        numeric.loc[unresolved] = pd.to_numeric(extracted, errors="coerce")
    return numeric


def suggest_outcome_columns(df: pd.DataFrame, labels: dict[str, str] | None = None) -> list[str]:
    """Candidatas a variable de resultado: columnas numéricas con recorrido
    amplio (escalas tipo Likert o 0-10), no binarias ni con solo un puñado de
    códigos categóricos (esas son más bien candidatas a atributo) y que no
    sean, por su nombre, un identificador de entrevistado.
    """
    candidates = []
    for col in df.columns:
        if _SCALE_META_SUFFIX_RE.search(col) or col.lower() in _ID_CANDIDATES:
            continue
        series = coerce_scale_numeric(df[col])
        n_valid = series.notna().sum()
        if n_valid == 0:
            continue
        n_levels = series.dropna().nunique()
        if n_levels >= 5:
            candidates.append(col)
    return candidates


def suggest_attribute_columns(df: pd.DataFrame, labels: dict[str, str] | None = None) -> list[str]:
    """Candidatas a atributo del estímulo: columnas con pocos niveles
    distintos (2-8), típico de una versión aleatorizada del estímulo
    (Texto A/B, Foto A/B...), a diferencia de una escala de resultado.
    """
    candidates = []
    for col in df.columns:
        series = df[col].dropna()
        if series.empty:
            continue
        n_levels = series.astype(str).nunique()
        if 2 <= n_levels <= 8:
            candidates.append(col)
    return candidates


def validate_vignette_config(df: pd.DataFrame, config: VignetteMappingConfig) -> list[str]:
    """Devuelve una lista de problemas (cadenas legibles). Lista vacía = ok."""
    issues: list[str] = []

    if config.respondent_id is not None and config.respondent_id not in df.columns:
        issues.append(f'La columna de identificador "{config.respondent_id}" no existe en el fichero.')

    if config.outcome_column is not None:
        if config.outcome_column not in df.columns:
            issues.append(f'La columna de resultado "{config.outcome_column}" no existe en el fichero.')
        else:
            n_numeric = coerce_scale_numeric(df[config.outcome_column]).notna().sum()
            if n_numeric == 0:
                issues.append(
                    f'La columna de resultado "{config.outcome_column}" no tiene ningún valor numérico.'
                )

    for attr in config.attributes:
        if attr.column not in df.columns:
            issues.append(f'La columna "{attr.column}" del atributo "{attr.name}" no existe en el fichero.')

    return issues


def run_vignette_ols(df: pd.DataFrame, config: VignetteMappingConfig, baselines: dict[str, str] | None = None) -> dict:
    if config.outcome_column is None:
        raise ValueError(
            'Este conjunto no tiene una única variable de resultado mapeada. Ve al paso '
            '"Tablas comparativas" y usa "Estimar batería" para estimar cada variable de la batería.'
        )
    baselines = baselines or {}
    attributes = config.attribute_names()
    column_by_attr = {a.name: a.column for a in config.attributes}

    sub = pd.DataFrame(index=df.index)
    sub["_outcome"] = coerce_scale_numeric(df[config.outcome_column])
    for attr, col in column_by_attr.items():
        sub[attr] = df[col]

    sub = sub.dropna(subset=["_outcome", *attributes])
    if sub.empty:
        raise ValueError("No quedan filas completas (sin valores perdidos) para estimar el modelo.")

    y = sub["_outcome"].astype(float)
    X, meta, baseline_map = build_design_matrix(sub, attributes, baselines)
    X = sm.add_constant(X, has_constant="add")

    try:
        model = sm.OLS(y, X).fit(cov_type="HC1")
    except Exception as e:
        raise ValueError(f"No se pudo estimar el modelo OLS: {e}")

    conf_int = model.conf_int()
    return {
        "method": "vignette_ols",
        "n": int(model.nobs),
        "r_squared": float(model.rsquared),
        "outcome_mean": float(y.mean()),
        "baselines": baseline_map,
        "coefficients": format_coefficients(model.params, model.bse, model.pvalues, conf_int, meta),
    }


def run_vignette_battery(
    df: pd.DataFrame,
    config: VignetteMappingConfig,
    outcome_columns: list[str],
    outcome_labels: dict[str, str] | None = None,
    attributes: list[str] | None = None,
    baselines: dict[str, str] | None = None,
) -> dict:
    """Repite `run_vignette_ols` una vez por cada columna de `outcome_columns`,
    reutilizando los mismos atributos ya mapeados en `config` y cambiando
    solo la variable de resultado en cada pasada. Pensado para experimentos
    donde cada entrevistado responde una batería de preguntas (a menudo
    escalas Likert) sobre el único estímulo que le tocó, en vez de tener una
    sola variable dependiente: así se puede comparar, de una vez, cómo el
    mismo atributo del estímulo mueve cada pregunta de la batería.

    Las columnas que no se puedan tratar como escala numérica (o que se
    queden sin filas completas tras quitar los valores perdidos) se omiten
    en `skipped` con el motivo, en vez de abortar toda la batería: es
    frecuente que alguna pregunta de la batería sea categórica pura o tenga
    una tasa de no-respuesta distinta a las demás.
    """
    outcome_labels = outcome_labels or {}
    selected_attrs = attributes or config.attribute_names()
    restricted_config = config.model_copy(
        update={"attributes": [a for a in config.attributes if a.name in selected_attrs]}
    )

    results = []
    skipped = []
    for outcome_col in outcome_columns:
        outcome_label = outcome_labels.get(outcome_col, outcome_col)
        per_outcome_config = restricted_config.model_copy(
            update={"outcome_column": outcome_col, "outcome_label": outcome_label}
        )
        issues = validate_vignette_config(df, per_outcome_config)
        if issues:
            skipped.append({"outcome_column": outcome_col, "outcome_label": outcome_label, "reason": "; ".join(issues)})
            continue
        try:
            result = run_vignette_ols(df, per_outcome_config, baselines)
        except ValueError as e:
            skipped.append({"outcome_column": outcome_col, "outcome_label": outcome_label, "reason": str(e)})
            continue
        result["outcome_column"] = outcome_col
        result["outcome_label"] = outcome_label
        results.append(result)

    return {"method": "vignette_battery", "results": results, "skipped": skipped}
