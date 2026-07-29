"""Tests de integración de la API para las tablas descriptivas de un
conjunto de viñeta: comparar varias variables de resultado por el atributo
mapeado (sin tener que elegir una única variable dependiente ni volver a
mapear nada), conjuntos de respuesta múltiple, y recodificación de
variables numéricas a dicotómicas.
"""
import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _make_vignette_csv() -> bytes:
    rng = np.random.default_rng(0)
    n = 60
    rows = []
    for rid in range(n):
        texto = rng.choice(["Texto A", "Texto B"])
        gravedad = float(np.clip(rng.normal(5 + (2 if texto == "Texto B" else 0), 1.5), 0, 10).round())
        justicia = float(np.clip(rng.normal(5, 2), 0, 10).round())
        rows.append({
            "id": f"R{rid}",
            "texto_mostrado": texto,
            "gravedad": gravedad,
            "justicia": justicia,
            "motivo_1": 1 if rng.random() < 0.5 else None,
            "motivo_2": 1 if rng.random() < 0.3 else None,
            "motivo_3": 1 if rng.random() < 0.1 else None,
        })
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def _upload_and_map_vignette(client):
    content = _make_vignette_csv()
    r = client.post("/api/upload", files={"file": ("vinieta.csv", content, "text/csv")})
    assert r.status_code == 200, r.text
    data = r.json()
    session_id = data["session_id"]

    r = client.post(f"/api/experiments/{session_id}", json={"name": "Viñeta", "kind": "vignette"})
    experiment_id = r.json()["id"]

    apply_payload = {
        "outcome_column": "gravedad",
        "attributes": [{"name": "texto", "label": "Texto mostrado", "column": "texto_mostrado"}],
    }
    r = client.post(f"/api/vignette/{session_id}/{experiment_id}/apply", json=apply_payload)
    assert r.status_code == 200, r.text
    return session_id, experiment_id


def test_crosstab_covers_any_outcome_not_just_the_mapped_one(client):
    session_id, experiment_id = _upload_and_map_vignette(client)

    r = client.post(
        f"/api/vignette/{session_id}/{experiment_id}/crosstab",
        json={"outcome_columns": ["gravedad", "justicia"]},
    )
    assert r.status_code == 200, r.text
    tables = r.json()["tables"]
    assert len(tables) == 2  # una tabla por variable x atributo mapeado (aquí solo hay un atributo)
    outcome_cols = {t["outcome_column"] for t in tables}
    assert outcome_cols == {"gravedad", "justicia"}
    gravedad_table = next(t for t in tables if t["outcome_column"] == "gravedad")
    assert gravedad_table["group_column"] == "texto_mostrado"
    assert gravedad_table["numeric_summary"]["Texto B"]["mean"] > gravedad_table["numeric_summary"]["Texto A"]["mean"]


def test_crosstab_rejects_unknown_column(client):
    session_id, experiment_id = _upload_and_map_vignette(client)
    r = client.post(
        f"/api/vignette/{session_id}/{experiment_id}/crosstab",
        json={"outcome_columns": ["no_existe"]},
    )
    assert r.status_code == 400


def test_crosstab_requires_mapping_applied_first(client):
    content = _make_vignette_csv()
    r = client.post("/api/upload", files={"file": ("vinieta.csv", content, "text/csv")})
    session_id = r.json()["session_id"]
    r = client.post(f"/api/experiments/{session_id}", json={"name": "Viñeta", "kind": "vignette"})
    experiment_id = r.json()["id"]

    r = client.post(
        f"/api/vignette/{session_id}/{experiment_id}/crosstab",
        json={"outcome_columns": ["gravedad"]},
    )
    assert r.status_code == 400


def test_multi_response_summary_grouped_by_mapped_attribute(client):
    session_id, experiment_id = _upload_and_map_vignette(client)

    payload = {
        "items": [
            {"column": "motivo_1", "label": "Motivo 1"},
            {"column": "motivo_2", "label": "Motivo 2"},
            {"column": "motivo_3", "label": "Motivo 3"},
        ],
        "group_attribute": "texto",
    }
    r = client.post(f"/api/vignette/{session_id}/{experiment_id}/multi-response", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base_n"] > 0
    assert len(body["overall"]) == 3
    assert set(body["by_group"].keys()) == {"Texto A", "Texto B"}


def test_multi_response_rejects_unknown_group_attribute(client):
    session_id, experiment_id = _upload_and_map_vignette(client)
    payload = {"items": [{"column": "motivo_1", "label": "Motivo 1"}], "group_attribute": "no_existe"}
    r = client.post(f"/api/vignette/{session_id}/{experiment_id}/multi-response", json=payload)
    assert r.status_code == 400


def test_recode_creates_dichotomous_column_available_everywhere(client):
    session_id, experiment_id = _upload_and_map_vignette(client)

    payload = {
        "source_column": "gravedad",
        "new_column": "gravedad_bin",
        "new_label": "Gravedad (dicotómica)",
        "operator": ">=",
        "threshold": 8,
        "true_label": "Grave",
        "false_label": "No grave",
    }
    r = client.post(f"/api/columns/{session_id}/recode", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(c["name"] == "gravedad_bin" for c in body["columns"])

    # La nueva columna se puede usar de inmediato en la tabla cruzada de este conjunto.
    r = client.post(
        f"/api/vignette/{session_id}/{experiment_id}/crosstab",
        json={"outcome_columns": ["gravedad_bin"]},
    )
    assert r.status_code == 200, r.text
    table = r.json()["tables"][0]
    assert set(table["row_levels"]) <= {"Grave", "No grave"}


def test_recode_rejects_duplicate_column_name(client):
    session_id, experiment_id = _upload_and_map_vignette(client)
    payload = {
        "source_column": "gravedad",
        "new_column": "gravedad",  # ya existe
        "operator": ">=",
        "threshold": 8,
    }
    r = client.post(f"/api/columns/{session_id}/recode", json=payload)
    assert r.status_code == 400


def test_recode_rejects_non_numeric_source(client):
    session_id, experiment_id = _upload_and_map_vignette(client)
    payload = {
        "source_column": "texto_mostrado",
        "new_column": "texto_bin",
        "operator": ">=",
        "threshold": 1,
    }
    r = client.post(f"/api/columns/{session_id}/recode", json=payload)
    assert r.status_code == 400
