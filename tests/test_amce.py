from app.amce import run_clogit_amce, run_ols_amce, to_plot_rows
from app.reshape import wide_to_long
from tests.conftest import make_mapping_config, make_wide_df


def _amce_row(result, attribute, level):
    return next(c for c in result["coefficients"] if c["attribute"] == attribute and c["level"] == level)


def test_ols_amce_recovers_positive_role_effect():
    config = make_mapping_config(n_tasks=6)
    wide_df = make_wide_df(n_respondents=250, n_tasks=6, role_effect=1.5)
    long_df = wide_to_long(wide_df, config)

    result = run_ols_amce(long_df, attributes=["rol", "genero"])
    assert result["method"] == "ols"
    assert result["n"] == len(long_df.dropna(subset=["chosen"]))

    policia_row = _amce_row(result, "rol", "policia")
    assert policia_row["estimate"] > 0
    assert policia_row["p_value"] < 0.05


def test_ols_amce_null_effect_not_significant():
    config = make_mapping_config(n_tasks=6)
    wide_df = make_wide_df(n_respondents=250, n_tasks=6, role_effect=0.0, seed=7)
    long_df = wide_to_long(wide_df, config)

    result = run_ols_amce(long_df, attributes=["rol", "genero"])
    genero_row = _amce_row(result, "genero", "mujer")
    assert abs(genero_row["estimate"]) < 0.15


def test_clogit_amce_recovers_positive_role_effect():
    config = make_mapping_config(n_tasks=6)
    wide_df = make_wide_df(n_respondents=250, n_tasks=6, role_effect=1.5)
    long_df = wide_to_long(wide_df, config)

    result = run_clogit_amce(long_df, attributes=["rol", "genero"])
    assert result["method"] == "clogit"

    policia_row = _amce_row(result, "rol", "policia")
    assert policia_row["estimate"] > 0
    assert policia_row["p_value"] < 0.05


def test_to_plot_rows_includes_baseline_reference():
    config = make_mapping_config(n_tasks=4)
    wide_df = make_wide_df(n_respondents=150, n_tasks=4, role_effect=1.0)
    long_df = wide_to_long(wide_df, config)

    result = run_ols_amce(long_df, attributes=["rol", "genero"])
    plot_rows = to_plot_rows(result)

    baselines = [r for r in plot_rows if r["is_baseline"]]
    assert {r["attribute"] for r in baselines} == {"rol", "genero"}
    assert all(r["estimate"] == 0.0 for r in baselines)
    assert all(r["ci_low"] is None for r in baselines)
