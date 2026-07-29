import numpy as np
import pandas as pd
import pytest

from app.crosstab import build_crosstab, build_multi_response_summary


@pytest.fixture
def vignette_df():
    rng = np.random.default_rng(0)
    n = 60
    texto = rng.choice(["Texto A", "Texto B"], size=n)
    # "Texto B" empuja la gravedad percibida más alta, a propósito.
    gravedad = np.clip(rng.normal(5 + np.where(texto == "Texto B", 2, 0), 1.5), 0, 10).round()
    categoria = np.where(gravedad >= 7, "Muy grave", "Poco grave")
    return pd.DataFrame({"texto": texto, "gravedad": gravedad, "categoria": categoria})


def test_build_crosstab_numeric_outcome_includes_summary_stats(vignette_df):
    table = build_crosstab(vignette_df, "gravedad", "Gravedad percibida", "texto", "Texto mostrado")
    assert table["group_levels"] == ["Texto A", "Texto B"]
    assert table["numeric_summary"] is not None
    assert table["numeric_summary"]["Texto B"]["mean"] > table["numeric_summary"]["Texto A"]["mean"]
    assert table["n"] == len(vignette_df)
    # Los totales de columna deben coincidir con el nº de personas que vieron cada texto.
    assert sum(table["column_totals"].values()) == len(vignette_df)


def test_build_crosstab_categorical_outcome_has_no_numeric_summary(vignette_df):
    table = build_crosstab(vignette_df, "categoria", "Categoría", "texto", "Texto mostrado")
    assert table["numeric_summary"] is None
    assert set(table["row_levels"]) == {"Muy grave", "Poco grave"}
    # Cada columna (nivel de "texto") debe sumar al 100% entre las filas.
    for level in table["group_levels"]:
        total_pct = sum(table["percentages"][row][level] for row in table["row_levels"])
        assert total_pct == pytest.approx(100.0)


def test_build_crosstab_drops_missing_values():
    df = pd.DataFrame({
        "outcome": [1, 2, None, 3],
        "group": ["A", "A", "B", None],
    })
    table = build_crosstab(df, "outcome", "Outcome", "group", "Group")
    assert table["n"] == 2  # solo las dos primeras filas tienen ambos valores


def test_build_crosstab_sorts_rows_with_labelled_scale_endpoints():
    """Regresión: SPSS suele etiquetar solo los extremos de una escala
    ("10 Muy grave", "0 Nada grave") dejando los códigos intermedios como
    número puro; ordenar las filas con `float()` directo sobre esas
    etiquetas revienta. Hay que ordenar por el valor ya coaccionado a
    número, no por el texto crudo.
    """
    df = pd.DataFrame({
        "gravedad": ["10 Muy grave", "5", "10 Muy grave", "0 Nada grave", "8"],
        "texto": ["A", "B", "A", "B", "A"],
    })
    table = build_crosstab(df, "gravedad", "Gravedad", "texto", "Texto")
    assert table["row_levels"] == ["0 Nada grave", "5", "8", "10 Muy grave"]


def test_build_crosstab_empty_when_no_overlap():
    df = pd.DataFrame({"outcome": [None, None], "group": ["A", "B"]})
    table = build_crosstab(df, "outcome", "Outcome", "group", "Group")
    assert table["n"] == 0
    assert table["counts"] == {}


@pytest.fixture
def multi_response_df():
    return pd.DataFrame({
        "texto": ["A", "A", "B", "B", "A"],
        "motivo_1": [1, None, 1, None, 1],   # 3 de 5
        "motivo_2": [None, None, 1, 1, None],  # 2 de 5
        "motivo_3": [None, None, None, None, None],  # 0 de 5
    })


def test_multi_response_summary_counts_any_non_null_as_selected(multi_response_df):
    items = [
        {"column": "motivo_1", "label": "Motivo 1"},
        {"column": "motivo_2", "label": "Motivo 2"},
        {"column": "motivo_3", "label": "Motivo 3"},
    ]
    result = build_multi_response_summary(multi_response_df, items)
    # La fila 1 (índice 1) no tiene ninguna respuesta en el conjunto, así que
    # queda fuera de la base (4 de 5 entrevistados respondieron algo).
    assert result["base_n"] == 4
    by_col = {r["column"]: r for r in result["overall"]}
    assert by_col["motivo_1"]["n"] == 3
    assert by_col["motivo_2"]["n"] == 2
    assert by_col["motivo_3"]["n"] == 0
    assert by_col["motivo_1"]["pct_of_cases"] == pytest.approx(75.0)


def test_multi_response_summary_sorted_descending_by_n(multi_response_df):
    items = [
        {"column": "motivo_3", "label": "Motivo 3"},
        {"column": "motivo_1", "label": "Motivo 1"},
        {"column": "motivo_2", "label": "Motivo 2"},
    ]
    result = build_multi_response_summary(multi_response_df, items)
    ordered_cols = [r["column"] for r in result["overall"]]
    assert ordered_cols == ["motivo_1", "motivo_2", "motivo_3"]


def test_multi_response_summary_by_group(multi_response_df):
    items = [{"column": "motivo_1", "label": "Motivo 1"}, {"column": "motivo_2", "label": "Motivo 2"}]
    result = build_multi_response_summary(multi_response_df, items, group_column="texto", group_label="Texto")
    assert set(result["by_group"].keys()) == {"A", "B"}
    by_col_a = {r["column"]: r for r in result["by_group"]["A"]["rows"]}
    by_col_b = {r["column"]: r for r in result["by_group"]["B"]["rows"]}
    assert by_col_a["motivo_1"]["n"] == 2  # filas 0,1,4 son "A"; motivo_1 no nulo en 0 y 4
    assert by_col_b["motivo_2"]["n"] == 2  # filas 2,3 son "B"; motivo_2 no nulo en ambas


def test_multi_response_summary_respects_explicit_selected_value():
    df = pd.DataFrame({"opcion": ["1", "2", "1", "2"]})
    items = [{"column": "opcion", "label": "Opción", "selected_value": "1"}]
    result = build_multi_response_summary(df, items)
    assert result["overall"][0]["n"] == 2
    assert result["base_n"] == 4
