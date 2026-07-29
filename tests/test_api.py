"""Tests de integración de la API sobre el modelo de "varios conjuntos por
sesión": una misma sesión debe poder mantener a la vez un conjunto de
elección y uno o varios de viñeta, cada uno con su propio filtro de
submuestra, sin que uno interfiera con el otro.
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


def _make_mixed_csv() -> bytes:
    """Un fichero con dos experimentos administrados a submuestras distintas
    de la misma encuesta, marcadas con una columna EXPERIMENTO — la misma
    forma que el fichero .sav real que motivó este cambio: un conjoint de
    elección (EXPERIMENTO=1) y una viñeta de perfil único (EXPERIMENTO=2).
    """
    rng = np.random.default_rng(0)
    rows = []
    # Submuestra 1: conjoint de elección (cj1_A_rol/cj1_B_rol + cj1_eleccion).
    for rid in range(60):
        rol_a, rol_b = rng.choice(["policia", "medico"], size=2, replace=True)
        rows.append({
            "id": f"E1-{rid}",
            "EXPERIMENTO": 1,
            "cj1_A_rol": rol_a,
            "cj1_B_rol": rol_b,
            "cj1_eleccion": "A" if rol_a == "policia" else "B",
            "texto_version": np.nan,
            "gravedad": np.nan,
        })
    # Submuestra 2: viñeta (un texto A/B mostrado, valorado en una escala 0-10).
    for rid in range(60):
        texto = rng.choice(["A", "B"])
        gravedad = rng.normal(5 + (2 if texto == "B" else 0), 1)
        rows.append({
            "id": f"E2-{rid}",
            "EXPERIMENTO": 2,
            "cj1_A_rol": np.nan,
            "cj1_B_rol": np.nan,
            "cj1_eleccion": np.nan,
            "texto_version": texto,
            "gravedad": gravedad,
        })
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def _upload_mixed(client):
    content = _make_mixed_csv()
    r = client.post("/api/upload", files={"file": ("mixto.csv", content, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_creates_a_default_conjoint_experiment(client):
    data = _upload_mixed(client)
    assert len(data["experiments"]) == 1
    assert data["experiments"][0]["kind"] == "conjoint"
    assert data["default_experiment_id"] == data["experiments"][0]["id"]
    # El conjoint por defecto detecta cj1 aunque haya filas de la otra submuestra sin rellenar.
    assert data["suggested_mapping"]["tasks"] == ["cj1"]


def test_can_add_a_second_vignette_experiment_alongside_the_conjoint(client):
    data = _upload_mixed(client)
    session_id = data["session_id"]

    r = client.post(f"/api/experiments/{session_id}", json={"name": "Viñeta", "kind": "vignette"})
    assert r.status_code == 200, r.text
    vignette_id = r.json()["id"]

    r = client.get(f"/api/experiments/{session_id}")
    kinds = {e["id"]: e["kind"] for e in r.json()["experiments"]}
    assert kinds[data["default_experiment_id"]] == "conjoint"
    assert kinds[vignette_id] == "vignette"


def test_sample_filter_restricts_the_experiment_to_its_own_submuestra(client):
    data = _upload_mixed(client)
    session_id = data["session_id"]
    conjoint_id = data["default_experiment_id"]

    r = client.patch(
        f"/api/experiments/{session_id}/{conjoint_id}",
        json={"sample_filter": {"column": "EXPERIMENTO", "values": ["1"]}},
    )
    assert r.status_code == 200, r.text

    r = client.get(f"/api/mapping/{session_id}/{conjoint_id}/suggest")
    suggestion = r.json()
    payload = {
        "respondent_id": suggestion["respondent_id"],
        "tasks": suggestion["tasks"],
        "profiles": suggestion["profiles"],
        "attributes": suggestion["attributes"],
        "choice_columns": suggestion["choice_columns"],
        "choice_value_map": suggestion["choice_value_map"],
    }
    r = client.post(f"/api/mapping/{session_id}/{conjoint_id}/apply", json=payload)
    assert r.status_code == 200, r.text
    summary = r.json()["summary"]
    # Solo las 60 filas de EXPERIMENTO=1 entran en el conjunto, no las 120 del fichero completo.
    assert summary["n_respondents"] == 60


def test_vignette_experiment_end_to_end(client):
    data = _upload_mixed(client)
    session_id = data["session_id"]

    r = client.post(f"/api/experiments/{session_id}", json={"name": "Viñeta gravedad", "kind": "vignette"})
    vignette_id = r.json()["id"]

    r = client.patch(
        f"/api/experiments/{session_id}/{vignette_id}",
        json={"sample_filter": {"column": "EXPERIMENTO", "values": ["2"]}},
    )
    assert r.status_code == 200, r.text

    r = client.get(f"/api/vignette/{session_id}/{vignette_id}/suggest")
    assert r.status_code == 200, r.text
    suggestion = r.json()
    assert "gravedad" in suggestion["candidate_outcome_columns"]
    assert "texto_version" in suggestion["candidate_attribute_columns"]

    apply_payload = {
        "outcome_column": "gravedad",
        "attributes": [{"name": "texto", "label": "Texto mostrado", "column": "texto_version"}],
    }
    r = client.post(f"/api/vignette/{session_id}/{vignette_id}/apply", json=apply_payload)
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["n_valid_rows"] == 60

    r = client.post(f"/api/vignette/{session_id}/{vignette_id}/estimate", json={})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["n"] == 60
    row_b = next(c for c in result["coefficients"] if c["level"] == "B")
    assert row_b["estimate"] > 0
    assert row_b["p_value"] < 0.05


def test_conjoint_endpoint_rejects_vignette_experiment(client):
    data = _upload_mixed(client)
    session_id = data["session_id"]
    r = client.post(f"/api/experiments/{session_id}", json={"name": "Viñeta", "kind": "vignette"})
    vignette_id = r.json()["id"]

    r = client.get(f"/api/mapping/{session_id}/{vignette_id}/suggest")
    assert r.status_code == 400


def test_duplicate_experiment_copies_mapping_as_starting_point(client):
    data = _upload_mixed(client)
    session_id = data["session_id"]
    conjoint_id = data["default_experiment_id"]

    r = client.post(f"/api/experiments/{session_id}/{conjoint_id}/duplicate", json={"name": "Copia"})
    assert r.status_code == 200, r.text
    duplicate = r.json()
    assert duplicate["name"] == "Copia"
    assert duplicate["kind"] == "conjoint"
    assert duplicate["id"] != conjoint_id


def test_delete_experiment_removes_it_from_the_list(client):
    data = _upload_mixed(client)
    session_id = data["session_id"]
    r = client.post(f"/api/experiments/{session_id}", json={"name": "Temporal", "kind": "vignette"})
    temp_id = r.json()["id"]

    r = client.delete(f"/api/experiments/{session_id}/{temp_id}")
    assert r.status_code == 200

    r = client.get(f"/api/experiments/{session_id}")
    ids = {e["id"] for e in r.json()["experiments"]}
    assert temp_id not in ids


def _apply_default_conjoint_mapping(client, session_id, experiment_id):
    r = client.get(f"/api/mapping/{session_id}/{experiment_id}/suggest")
    suggestion = r.json()
    payload = {
        "respondent_id": suggestion["respondent_id"],
        "tasks": suggestion["tasks"],
        "profiles": suggestion["profiles"],
        "attributes": suggestion["attributes"],
        "choice_columns": suggestion["choice_columns"],
        "choice_value_map": suggestion["choice_value_map"],
    }
    r = client.post(f"/api/mapping/{session_id}/{experiment_id}/apply", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("fmt,content_type_fragment", [
    ("csv", "text/csv"),
    ("xlsx", "spreadsheetml"),
    ("sav", "octet-stream"),
    ("dta", "octet-stream"),
])
def test_download_reshaped_conjoint_in_every_format(client, fmt, content_type_fragment):
    data = _upload_mixed(client)
    session_id = data["session_id"]
    conjoint_id = data["default_experiment_id"]
    _apply_default_conjoint_mapping(client, session_id, conjoint_id)

    r = client.get(f"/api/reshape/{session_id}/{conjoint_id}/download?format={fmt}")
    assert r.status_code == 200, r.text
    assert content_type_fragment in r.headers["content-type"]
    assert f'.{fmt}"' in r.headers["content-disposition"]
    assert len(r.content) > 0


def test_download_reshaped_rejects_unknown_format(client):
    data = _upload_mixed(client)
    session_id = data["session_id"]
    conjoint_id = data["default_experiment_id"]
    _apply_default_conjoint_mapping(client, session_id, conjoint_id)

    r = client.get(f"/api/reshape/{session_id}/{conjoint_id}/download?format=pdf")
    assert r.status_code == 400


def test_apply_mapping_summary_includes_unmapped_choice_classification(client):
    data = _upload_mixed(client)
    session_id = data["session_id"]
    conjoint_id = data["default_experiment_id"]
    result = _apply_default_conjoint_mapping(client, session_id, conjoint_id)
    assert "unmapped_choice_values" in result["summary"]
    assert result["summary"]["unmapped_choice_values"] == {"missing_like": [], "unrecognized": []}


def test_download_vignette_data(client):
    data = _upload_mixed(client)
    session_id = data["session_id"]
    r = client.post(f"/api/experiments/{session_id}", json={"name": "Viñeta", "kind": "vignette"})
    vignette_id = r.json()["id"]
    client.patch(
        f"/api/experiments/{session_id}/{vignette_id}",
        json={"sample_filter": {"column": "EXPERIMENTO", "values": ["2"]}},
    )
    apply_payload = {
        "outcome_column": "gravedad",
        "attributes": [{"name": "texto", "label": "Texto mostrado", "column": "texto_version"}],
    }
    r = client.post(f"/api/vignette/{session_id}/{vignette_id}/apply", json=apply_payload)
    assert r.status_code == 200, r.text

    r = client.get(f"/api/vignette/{session_id}/{vignette_id}/download?format=xlsx")
    assert r.status_code == 200, r.text
    assert "spreadsheetml" in r.headers["content-type"]
