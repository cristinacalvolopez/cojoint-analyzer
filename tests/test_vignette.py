import numpy as np
import pandas as pd
import pytest

from app.schema import VignetteAttributeMapping, VignetteMappingConfig
from app.vignette import (
    coerce_scale_numeric,
    run_vignette_battery,
    run_vignette_ols,
    suggest_attribute_columns,
    suggest_outcome_columns,
    validate_vignette_config,
)


@pytest.fixture
def vignette_df():
    rng = np.random.default_rng(1)
    n = 200
    texto = rng.choice(["A", "B"], size=n)
    gravedad = rng.normal(5 + np.where(texto == "B", 2.0, 0.0), 1)
    return pd.DataFrame({
        "id": np.arange(n),  # identificador casi único: no debe sugerirse como resultado
        "foto_version": rng.choice(["A", "B"], size=n),
        "texto_version": texto,
        "gravedad": gravedad,
    })


@pytest.fixture
def battery_df(vignette_df):
    """Misma viñeta, pero con una batería de preguntas: dos escalas más que
    reaccionan al mismo atributo `texto_version` (una con efecto fuerte, otra
    sin apenas efecto) y una columna puramente categórica sin relación con
    ninguna escala, que debería omitirse en vez de romper la batería entera.
    """
    df = vignette_df.copy()
    rng = np.random.default_rng(2)
    n = len(df)
    df["justicia"] = rng.normal(5 + np.where(df["texto_version"] == "B", 3.0, 0.0), 1)
    df["confianza"] = rng.normal(5, 1)  # sin relación con el atributo
    df["comentario_libre"] = rng.choice(["me parece bien", "no sé", "no contesto"], size=n)
    return df


def test_suggest_outcome_columns_excludes_id_like_columns(vignette_df):
    candidates = suggest_outcome_columns(vignette_df)
    assert "gravedad" in candidates
    assert "id" not in candidates


def test_suggest_attribute_columns_finds_low_cardinality_columns(vignette_df):
    candidates = suggest_attribute_columns(vignette_df)
    assert "texto_version" in candidates
    assert "foto_version" in candidates
    assert "gravedad" not in candidates  # recorrido continuo, no un puñado de niveles


def test_validate_vignette_config_flags_missing_columns(vignette_df):
    config = VignetteMappingConfig(
        outcome_column="no_existe",
        attributes=[VignetteAttributeMapping(name="texto", column="tampoco_existe")],
    )
    issues = validate_vignette_config(vignette_df, config)
    assert any("no_existe" in i for i in issues)
    assert any("tampoco_existe" in i for i in issues)


def test_run_vignette_ols_recovers_known_effect(vignette_df):
    config = VignetteMappingConfig(
        outcome_column="gravedad",
        attributes=[VignetteAttributeMapping(name="texto", label="Texto", column="texto_version")],
    )
    result = run_vignette_ols(vignette_df, config)
    assert result["method"] == "vignette_ols"
    assert result["n"] == len(vignette_df)
    row_b = next(c for c in result["coefficients"] if c["level"] == "B")
    assert row_b["estimate"] > 1.0
    assert row_b["p_value"] < 0.05


def test_coerce_scale_numeric_handles_labelled_scale_endpoints():
    """Regresión: SPSS suele etiquetar solo los extremos de una escala 0-10
    (p. ej. "10 Muy grave"/"0 Nada grave") y dejar los códigos intermedios
    como número puro. `pd.to_numeric` directo pierde justo esos extremos, que
    en la práctica son las respuestas más frecuentes de cualquier escala.
    """
    series = pd.Series(["10 Muy grave", "9", "8", "0 Nada grave", None])
    result = coerce_scale_numeric(series)
    assert result.tolist()[:4] == [10.0, 9.0, 8.0, 0.0]
    assert pd.isna(result.iloc[4])


def test_suggest_outcome_columns_recovers_scale_with_labelled_endpoints():
    values = ["10 Muy grave"] * 40 + ["9"] * 5 + ["8"] * 2 + ["5"] + ["0 Nada grave"] * 2
    df = pd.DataFrame({"gravedad": pd.Categorical(values)})
    candidates = suggest_outcome_columns(df)
    assert "gravedad" in candidates


def test_run_vignette_ols_raises_when_no_complete_rows():
    df = pd.DataFrame({"outcome": [None, None], "attr": ["A", "B"]})
    config = VignetteMappingConfig(
        outcome_column="outcome",
        attributes=[VignetteAttributeMapping(name="attr", column="attr")],
    )
    with pytest.raises(ValueError, match="No quedan filas completas"):
        run_vignette_ols(df, config)


def test_run_vignette_battery_estimates_each_outcome_and_skips_non_numeric(battery_df):
    config = VignetteMappingConfig(
        outcome_column="gravedad",  # se sustituye por cada outcome_column de la batería
        attributes=[VignetteAttributeMapping(name="texto", label="Texto", column="texto_version")],
    )
    result = run_vignette_battery(
        battery_df,
        config,
        outcome_columns=["gravedad", "justicia", "confianza", "comentario_libre"],
        outcome_labels={"gravedad": "Gravedad percibida", "justicia": "Justicia de la sentencia"},
    )
    assert result["method"] == "vignette_battery"
    assert {r["outcome_column"] for r in result["results"]} == {"gravedad", "justicia", "confianza"}
    assert {s["outcome_column"] for s in result["skipped"]} == {"comentario_libre"}

    justicia_result = next(r for r in result["results"] if r["outcome_column"] == "justicia")
    assert justicia_result["outcome_label"] == "Justicia de la sentencia"
    row_b = next(c for c in justicia_result["coefficients"] if c["level"] == "B")
    assert row_b["estimate"] > 2.0
    assert row_b["p_value"] < 0.05

    # "confianza" no tiene relación real con el atributo, pero al ser una
    # escala numérica válida no debe omitirse de la batería (solo se omiten
    # columnas que no se puedan tratar como escala, no efectos no
    # significativos): comprobamos que estimó, sin exigir un p-valor exacto
    # que sería una aserción frágil sobre ruido aleatorio.
    confianza_result = next(r for r in result["results"] if r["outcome_column"] == "confianza")
    assert any(c["level"] == "B" for c in confianza_result["coefficients"])


def test_run_vignette_battery_skips_all_when_no_outcomes_survive():
    df = pd.DataFrame({"attr": ["A", "B", "A", "B"], "solo_texto": ["x", "y", "z", "w"]})
    config = VignetteMappingConfig(
        outcome_column="solo_texto",
        attributes=[VignetteAttributeMapping(name="attr", column="attr")],
    )
    result = run_vignette_battery(df, config, outcome_columns=["solo_texto"])
    assert result["results"] == []
    assert result["skipped"][0]["outcome_column"] == "solo_texto"
