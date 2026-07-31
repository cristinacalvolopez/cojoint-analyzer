"""Tests de integración de la API para conjuntos de tipo "elección con
diseño externo": el fichero de respuestas solo trae qué perfil ganó cada
tarea y un código de versión aleatoria; los atributos reales viven en un
fichero de diseño aparte que hay que subir y cruzar por versión — el mismo
caso real que motivó esta funcionalidad (Experimento 1 del fichero .sav de
Cristina, con el diseño en `Diseno.xlsx`).
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


def _make_respondent_csv() -> bytes:
    rng = np.random.default_rng(0)
    n = 40
    rows = []
    for rid in range(n):
        version = rng.integers(1, 6)  # 5 versiones, a propósito de las del diseño
        row = {"id": f"R{rid}", "VERSION_CJ": f"Versión {version}"}
        for t in range(1, 4):  # 3 tareas
            row[f"EXP1_{t}"] = rng.choice(["Candidato/a 1", "Candidato/a 2"])
        rows.append(row)
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def _make_design_xlsx() -> bytes:
    rows = []
    professions = ["Médico/a", "Abogado/a", "Profesor/a", "Enfermero/a", "Ingeniero/a", "Periodista"]
    i = 0
    for version in range(1, 6):
        for pantalla in range(1, 4):
            for concepto in (1, 2):
                rows.append({
                    "Versión": version, "Pantalla": pantalla, "Concepto": concepto,
                    "Profesión": professions[i % len(professions)],
                })
                i += 1
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Diseño")
    return buf.getvalue()


def _upload_respondent(client) -> dict:
    content = _make_respondent_csv()
    r = client.post("/api/upload", files={"file": ("respuestas.csv", content, "text/csv")})
    assert r.status_code == 200, r.text
    data = r.json()
    # Subir el fichero ya no crea ningún conjunto por defecto: se crea uno de
    # elección aquí mismo, para no tocar el resto de este fichero de tests
    # (solo test_apply_design_mapping_rejects_wrong_kind lo necesita).
    r = client.post(f"/api/experiments/{data['session_id']}", json={"name": "Conjunto 1", "kind": "conjoint"})
    assert r.status_code == 200, r.text
    data["default_experiment_id"] = r.json()["id"]
    return data


def _create_design_experiment(client, session_id) -> str:
    r = client.post(f"/api/experiments/{session_id}", json={"name": "Experimento 1", "kind": "conjoint_design"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_experiment_creation_reports_no_design_file_yet(client):
    data = _upload_respondent(client)
    session_id = data["session_id"]
    experiment_id = _create_design_experiment(client, session_id)
    r = client.get(f"/api/experiments/{session_id}")
    exp = next(e for e in r.json()["experiments"] if e["id"] == experiment_id)
    assert exp["kind"] == "conjoint_design"
    assert exp["has_design_file"] is False


def test_upload_design_file_suggests_task_and_profile_columns(client):
    data = _upload_respondent(client)
    session_id = data["session_id"]
    experiment_id = _create_design_experiment(client, session_id)

    r = client.post(
        f"/api/design/{session_id}/{experiment_id}/upload",
        files={"file": ("Diseno.xlsx", _make_design_xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["design_task_column"] == "Pantalla"
    assert body["design_profile_column"] == "Concepto"
    assert "Profesión" in body["design_columns"]

    r = client.get(f"/api/experiments/{session_id}")
    exp = next(e for e in r.json()["experiments"] if e["id"] == experiment_id)
    assert exp["has_design_file"] is True


def test_suggest_mapping_finds_choice_columns_and_join_key(client):
    data = _upload_respondent(client)
    session_id = data["session_id"]
    experiment_id = _create_design_experiment(client, session_id)
    client.post(
        f"/api/design/{session_id}/{experiment_id}/upload",
        files={"file": ("Diseno.xlsx", _make_design_xlsx(), "application/octet-stream")},
    )

    r = client.get(
        f"/api/design/{session_id}/{experiment_id}/suggest",
        params={"task_column": "Pantalla", "profile_column": "Concepto"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tasks"] == ["1", "2", "3"]
    assert body["profiles"] == ["1", "2"]
    assert body["choice_columns"] == {"1": "EXP1_1", "2": "EXP1_2", "3": "EXP1_3"}
    assert body["choice_value_map"] == {"Candidato/a 1": "1", "Candidato/a 2": "2"}

    # "Versión" no se detecta por nombre exacto (el fichero de respuestas usa
    # "VERSION_CJ"), así que no debe aparecer como candidata automática, pero
    # sí debe poder añadirse a mano en el paso de aplicar el mapeo.
    join_candidate_cols = {jk["design_column"] for jk in body["join_key_candidates"]}
    assert "Versión" not in join_candidate_cols


def test_design_values_endpoint_suggests_value_map_for_manually_added_join_key(client):
    """"Versión" no se auto-detecta como clave de cruce (el nombre no coincide
    con "VERSION_CJ"), pero el endpoint de valores del diseño debe seguir
    proponiendo una correspondencia razonable cuando el usuario la añade a
    mano señalando la columna de respuestas correspondiente.
    """
    data = _upload_respondent(client)
    session_id = data["session_id"]
    experiment_id = _create_design_experiment(client, session_id)
    client.post(
        f"/api/design/{session_id}/{experiment_id}/upload",
        files={"file": ("Diseno.xlsx", _make_design_xlsx(), "application/octet-stream")},
    )

    r = client.get(f"/api/design/{session_id}/{experiment_id}/design-values", params={"column": "Versión"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["design_values"] == ["1", "2", "3", "4", "5"]

    r = client.get(
        f"/api/design/{session_id}/{experiment_id}/value-map-suggestion",
        params={"respondent_column": "VERSION_CJ", "design_column": "Versión"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["value_map"] == {f"Versión {i}": str(i) for i in range(1, 6)}


def test_apply_design_mapping_and_estimate_amce(client):
    data = _upload_respondent(client)
    session_id = data["session_id"]
    experiment_id = _create_design_experiment(client, session_id)
    client.post(
        f"/api/design/{session_id}/{experiment_id}/upload",
        files={"file": ("Diseno.xlsx", _make_design_xlsx(), "application/octet-stream")},
    )
    suggestion = client.get(
        f"/api/design/{session_id}/{experiment_id}/suggest",
        params={"task_column": "Pantalla", "profile_column": "Concepto"},
    ).json()

    payload = {
        "respondent_id": "id",
        "tasks": suggestion["tasks"],
        "profiles": suggestion["profiles"],
        "design_task_column": "Pantalla",
        "design_profile_column": "Concepto",
        "choice_columns": suggestion["choice_columns"],
        "choice_value_map": suggestion["choice_value_map"],
        "join_keys": [
            {"design_column": "Versión", "respondent_column": "VERSION_CJ", "value_map": {f"Versión {i}": str(i) for i in range(1, 6)}},
        ],
        "attributes": [{"name": "rol", "label": "Profesión", "design_column": "Profesión"}],
    }
    r = client.post(f"/api/design/{session_id}/{experiment_id}/apply", json=payload)
    assert r.status_code == 200, r.text
    summary = r.json()["summary"]
    assert summary["n_respondents"] == 40
    assert summary["n_tasks"] == 3
    assert summary["n_rows"] == 40 * 3 * 2

    r = client.post(f"/api/amce/{session_id}/{experiment_id}", json={"method": "ols", "attributes": None, "baselines": {}})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["n"] == 40 * 3 * 2
    assert len(result["coefficients"]) > 0

    # También se puede descargar el fichero ya cruzado y reestructurado.
    r = client.get(f"/api/reshape/{session_id}/{experiment_id}/download?format=xlsx")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]


def test_apply_design_mapping_rejects_wrong_kind(client):
    data = _upload_respondent(client)
    session_id = data["session_id"]
    conjoint_id = data["default_experiment_id"]
    r = client.get(f"/api/design/{session_id}/{conjoint_id}/suggest", params={"task_column": "x", "profile_column": "y"})
    assert r.status_code == 400
