import io
import os
import tempfile

import pandas as pd
import pyreadstat
import pytest
from fastapi.testclient import TestClient

from app.export import export_dataframe
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "respondent_id": ["R1", "R2", "R3"],
        "task": pd.Categorical(["cj1", "cj1", "cj2"]),
        "chosen": pd.array([0, 1, None], dtype="Int64"),
        "rol": pd.Categorical(["policía", "médico", "policía"]),  # con acentos, a propósito
    })


def test_export_csv_round_trips(sample_df):
    content, content_type = export_dataframe(sample_df, "csv")
    assert content_type == "text/csv"
    back = pd.read_csv(io.BytesIO(content))
    assert back["respondent_id"].tolist() == ["R1", "R2", "R3"]
    assert back["rol"].tolist() == ["policía", "médico", "policía"]


def test_export_xlsx_round_trips(sample_df):
    content, content_type = export_dataframe(sample_df, "xlsx")
    assert "spreadsheetml" in content_type
    back = pd.read_excel(io.BytesIO(content))
    assert back["respondent_id"].tolist() == ["R1", "R2", "R3"]
    assert back["rol"].tolist() == ["policía", "médico", "policía"]


def test_export_sav_round_trips(sample_df):
    content, content_type = export_dataframe(sample_df, "sav")
    assert content_type == "application/octet-stream"
    fd, path = tempfile.mkstemp(suffix=".sav")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(content)
        back, meta = pyreadstat.read_sav(path)
    finally:
        os.unlink(path)
    assert back["respondent_id"].tolist() == ["R1", "R2", "R3"]
    assert back["rol"].tolist() == ["policía", "médico", "policía"]


def test_export_dta_round_trips(sample_df):
    content, content_type = export_dataframe(sample_df, "dta")
    assert content_type == "application/octet-stream"
    fd, path = tempfile.mkstemp(suffix=".dta")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(content)
        back = pd.read_stata(path)
    finally:
        os.unlink(path)
    assert back["respondent_id"].tolist() == ["R1", "R2", "R3"]
    assert back["rol"].tolist() == ["policía", "médico", "policía"]


def test_export_rejects_unknown_format(sample_df):
    with pytest.raises(ValueError, match="no soportado"):
        export_dataframe(sample_df, "pdf")


def test_export_table_endpoint_xlsx(client):
    payload = {
        "rows": [
            {"Atributo": "rol", "Nivel": "policía", "Estimación": 0.12, "p": 0.03},
            {"Atributo": "rol", "Nivel": "médico (ref.)", "Estimación": 0, "p": None},
        ],
        "filename": "coeficientes_amce",
        "format": "xlsx",
    }
    r = client.post("/api/export/table", json=payload)
    assert r.status_code == 200, r.text
    assert "spreadsheetml" in r.headers["content-type"]
    back = pd.read_excel(io.BytesIO(r.content))
    assert back["Nivel"].tolist() == ["policía", "médico (ref.)"]


def test_export_table_endpoint_csv(client):
    payload = {"rows": [{"a": 1, "b": "x"}], "filename": "tabla", "format": "csv"}
    r = client.post("/api/export/table", json=payload)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "text/csv; charset=utf-8"


def test_export_table_endpoint_rejects_empty_rows(client):
    r = client.post("/api/export/table", json={"rows": [], "format": "xlsx"})
    assert r.status_code == 422
