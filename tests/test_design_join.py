import numpy as np
import pandas as pd
import pytest

from app import design_join as dj
from app.mapping import infer_choice_value_map
from app.schema import DesignJoinKey, ExternalDesignAttributeMapping, ExternalDesignMappingConfig


@pytest.fixture
def design_df():
    """Un diseño mínimo: 5 versiones x 2 pantallas x 2 conceptos, con un
    único atributo ("Profesión") para mantener el fixture legible. 5
    versiones (no 2) para que "Versión" no tenga la misma cardinalidad que
    "Concepto" y así no crear una ambigüedad artificial que no se daría en
    un diseño real (siempre con muchas más versiones que perfiles)."""
    professions = [
        "Médico/a", "Abogado/a", "Profesor/a", "Enfermero/a",
        "Ingeniero/a", "Periodista", "Dentista", "Psicólogo/a",
        "Investigador/a", "Farmacéutico/a", "Empresario/a", "Conserje",
        "Trabajador/a social", "Arquitecto/a", "Comercial de seguros", "Dependiente de tienda",
        "Médico/a", "Abogado/a", "Profesor/a", "Enfermero/a",
    ]
    rows = []
    i = 0
    for version in range(1, 6):
        for pantalla in (1, 2):
            for concepto in (1, 2):
                rows.append({
                    "Versión": version, "Pantalla": pantalla, "Concepto": concepto,
                    "Profesión": professions[i % len(professions)],
                })
                i += 1
    return pd.DataFrame(rows)


@pytest.fixture
def respondent_df():
    return pd.DataFrame({
        "id": ["R1", "R2", "R3"],
        "VERSION_CJ": ["Versión 1", "Versión 2", "Versión 1"],
        "EXP1_1": ["Candidato/a 1", "Candidato/a 2", "Candidato/a 1"],
        "EXP1_2": ["Candidato/a 2", "Candidato/a 1", "Candidato/a 2"],
    })


def _build_config(respondent_df, design_df):
    tasks = ["1", "2"]
    profiles = ["1", "2"]
    choice_columns = {"1": "EXP1_1", "2": "EXP1_2"}
    choice_value_map, _ = infer_choice_value_map(respondent_df, choice_columns, profiles)
    design_versions = sorted(design_df["Versión"].astype(str).unique())
    version_map, _ = dj.suggest_value_map(respondent_df, "VERSION_CJ", design_versions)
    return ExternalDesignMappingConfig(
        respondent_id="id",
        tasks=tasks,
        profiles=profiles,
        design_task_column="Pantalla",
        design_profile_column="Concepto",
        choice_columns=choice_columns,
        choice_value_map=choice_value_map,
        join_keys=[DesignJoinKey(design_column="Versión", respondent_column="VERSION_CJ", value_map=version_map)],
        attributes=[ExternalDesignAttributeMapping(name="rol", label="Profesión", design_column="Profesión")],
    )


def test_suggest_task_profile_columns_detects_by_name_and_cardinality(design_df):
    result = dj.suggest_task_profile_columns(design_df)
    assert result == {"design_task_column": "Pantalla", "design_profile_column": "Concepto"}


def test_suggest_choice_columns_picks_the_family_covering_all_tasks():
    respondent_df = pd.DataFrame({
        "P1": [1, 2], "P3": [3, 4],       # familia irrelevante: no cubre la tarea "2"
        "EXP1_1": ["a", "b"], "EXP1_2": ["c", "d"],
    })
    result = dj.suggest_choice_columns(respondent_df, ["1", "2"])
    assert result == {"1": "EXP1_1", "2": "EXP1_2"}


def test_suggest_choice_columns_returns_empty_when_ambiguous():
    """Si ninguna familia de columnas cubre todas las tareas pedidas (o hay
    varias igual de plausibles), no debe adivinar a ciegas."""
    respondent_df = pd.DataFrame({"P1": [1], "Q1": [2]})
    result = dj.suggest_choice_columns(respondent_df, ["1", "2", "3"])
    assert result == {}


def test_suggest_value_map_matches_exact_and_trailing_number():
    respondent_df = pd.DataFrame({"VERSION_CJ": ["Versión 1", "Versión 2", "Galicia"]})
    value_map, default = dj.suggest_value_map(respondent_df, "VERSION_CJ", ["1", "2"])
    assert value_map == {"Versión 1": "1", "Versión 2": "2"}
    assert default is None  # "Galicia" no encaja como número; no hay "cajón de sastre" aquí


def test_suggest_value_map_defaults_to_catch_all_value():
    respondent_df = pd.DataFrame({"CCAA": ["Galicia", "Aragón", "Madrid"]})
    value_map, default = dj.suggest_value_map(respondent_df, "CCAA", ["Galicia", "Resto CCAA"])
    assert value_map == {"Galicia": "Galicia"}
    assert default == "Resto CCAA"


def test_build_long_df_matches_shape_and_joins_attributes_correctly(respondent_df, design_df):
    config = _build_config(respondent_df, design_df)
    long_df = dj.build_long_df(respondent_df, design_df, config)

    assert len(long_df) == 3 * 2 * 2  # 3 entrevistados x 2 tareas x 2 perfiles
    assert set(long_df.columns) >= {"respondent_id", "task", "profile", "choice_set", "chosen", "rol"}

    row = long_df[(long_df["respondent_id"] == "R1") & (long_df["task"] == "1") & (long_df["profile"] == "1")]
    assert row.iloc[0]["rol"] == "Médico/a"  # R1 -> Versión 1, Pantalla 1, Concepto 1


def test_build_long_df_each_choice_set_has_exactly_one_chosen(respondent_df, design_df):
    config = _build_config(respondent_df, design_df)
    long_df = dj.build_long_df(respondent_df, design_df, config)
    per_set = long_df.groupby("choice_set")["chosen"].sum()
    assert (per_set == 1).all()


def test_validate_external_design_config_flags_missing_design_columns(respondent_df, design_df):
    config = _build_config(respondent_df, design_df)
    config.attributes[0].design_column = "no_existe"
    issues = dj.validate_external_design_config(respondent_df, design_df, config)
    assert any("no_existe" in i["text"] and i["severity"] == "warning" for i in issues)


def test_validate_external_design_config_reports_defaulted_join_values():
    respondent_df = pd.DataFrame({
        "id": ["R1", "R2"],
        "CCAA": ["Galicia", "Aragón"],
        "VERSION_CJ": ["Versión 1", "Versión 1"],
        "EXP1_1": ["Candidato/a 1", "Candidato/a 2"],
    })
    design_df = pd.DataFrame({
        "Versión": [1, 1], "Pantalla": [1, 1], "Concepto": [1, 2],
        "CCAA": ["Galicia", "Galicia"], "Profesión": ["Médico/a", "Abogado/a"],
    })
    config = ExternalDesignMappingConfig(
        respondent_id="id",
        tasks=["1"],
        profiles=["1", "2"],
        design_task_column="Pantalla",
        design_profile_column="Concepto",
        choice_columns={"1": "EXP1_1"},
        choice_value_map={"Candidato/a 1": "1", "Candidato/a 2": "2"},
        join_keys=[
            DesignJoinKey(design_column="CCAA", respondent_column="CCAA", value_map={"Galicia": "Galicia"}, default_design_value="Galicia"),
        ],
        attributes=[ExternalDesignAttributeMapping(name="rol", design_column="Profesión")],
    )
    issues = dj.validate_external_design_config(respondent_df, design_df, config)
    defaulted = [i for i in issues if "Aragón" in i["text"]]
    assert len(defaulted) == 1
    assert defaulted[0]["severity"] == "info"


def test_build_long_df_without_join_keys_uses_the_single_design_combination():
    """Si el diseño no varía por entrevistado (sin clave de cruce, p. ej. una
    única versión para todo el mundo), cada tarea+perfil tiene un solo valor
    de atributo que se aplica a todas las filas."""
    respondent_df = pd.DataFrame({
        "id": ["R1", "R2"],
        "EXP1_1": ["Candidato/a 1", "Candidato/a 2"],
    })
    design_df = pd.DataFrame({
        "Pantalla": [1, 1], "Concepto": [1, 2], "Profesión": ["Médico/a", "Abogado/a"],
    })
    config = ExternalDesignMappingConfig(
        respondent_id="id",
        tasks=["1"],
        profiles=["1", "2"],
        design_task_column="Pantalla",
        design_profile_column="Concepto",
        choice_columns={"1": "EXP1_1"},
        choice_value_map={"Candidato/a 1": "1", "Candidato/a 2": "2"},
        join_keys=[],
        attributes=[ExternalDesignAttributeMapping(name="rol", design_column="Profesión")],
    )
    long_df = dj.build_long_df(respondent_df, design_df, config)
    assert long_df[long_df["profile"] == "1"]["rol"].unique().tolist() == ["Médico/a"]
    assert long_df[long_df["profile"] == "2"]["rol"].unique().tolist() == ["Abogado/a"]
