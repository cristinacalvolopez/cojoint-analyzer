"""Genera un fichero ancho sintético con la misma forma que el estudio real
(tareas cj1..cjN, perfiles A/B, atributos rol/genero, columna de elección)
para probar el motor de reestructuración y la estimación del AMCE sin
depender de datos reales.
"""
import numpy as np
import pandas as pd
import pytest

from app.schema import AttributeMapping, ConjointMappingConfig

ROLES = ["policia", "medico", "profesor"]
GENEROS = ["hombre", "mujer"]


def make_wide_df(n_respondents: int = 120, n_tasks: int = 4, seed: int = 42, role_effect: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for rid in range(n_respondents):
        row = {"id_encuesta": f"R{rid:03d}"}
        for t in range(1, n_tasks + 1):
            rol_a, rol_b = rng.choice(ROLES, size=2, replace=True)
            gen_a, gen_b = rng.choice(GENEROS, size=2, replace=True)
            row[f"cj{t}_A_rol"] = rol_a
            row[f"cj{t}_B_rol"] = rol_b
            row[f"cj{t}_A_gen"] = gen_a
            row[f"cj{t}_B_gen"] = gen_b

            # Utilidad simulada: 'policia' añade role_effect a la probabilidad de ser elegido.
            util_a = role_effect * (rol_a == "policia") + rng.normal(0, 1)
            util_b = role_effect * (rol_b == "policia") + rng.normal(0, 1)
            row[f"cj{t}_eleccion"] = "A" if util_a > util_b else "B"
        rows.append(row)
    return pd.DataFrame(rows)


def make_mapping_config(n_tasks: int = 4) -> ConjointMappingConfig:
    tasks = [f"cj{t}" for t in range(1, n_tasks + 1)]
    return ConjointMappingConfig(
        respondent_id="id_encuesta",
        tasks=tasks,
        profiles=["A", "B"],
        attributes=[
            AttributeMapping(
                name="rol",
                label="Rol",
                columns={t: {"A": f"{t}_A_rol", "B": f"{t}_B_rol"} for t in tasks},
            ),
            AttributeMapping(
                name="genero",
                label="Género",
                columns={t: {"A": f"{t}_A_gen", "B": f"{t}_B_gen"} for t in tasks},
            ),
        ],
        choice_columns={t: f"{t}_eleccion" for t in tasks},
        choice_value_map={"A": "A", "B": "B"},
    )


@pytest.fixture
def wide_df():
    return make_wide_df()


@pytest.fixture
def mapping_config():
    return make_mapping_config()
