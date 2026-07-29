import io
import os
import tempfile

import pandas as pd
import pyreadstat
import pytest

from app.export import export_dataframe


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
