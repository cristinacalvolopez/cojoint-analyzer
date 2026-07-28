from app.mapping import validate_config
from app.reshape import reshape_summary, wide_to_long


def test_wide_to_long_shape(wide_df, mapping_config):
    long_df = wide_to_long(wide_df, mapping_config)
    n_tasks = len(mapping_config.tasks)
    n_profiles = len(mapping_config.profiles)
    assert len(long_df) == len(wide_df) * n_tasks * n_profiles
    assert set(long_df.columns) >= {"respondent_id", "task", "profile", "choice_set", "chosen", "rol", "genero"}


def test_each_choice_set_has_exactly_one_chosen_profile(wide_df, mapping_config):
    long_df = wide_to_long(wide_df, mapping_config)
    per_set = long_df.groupby("choice_set")["chosen"].sum()
    assert (per_set == 1).all()


def test_attribute_values_match_source_columns(wide_df, mapping_config):
    long_df = wide_to_long(wide_df, mapping_config)
    row0 = long_df[(long_df["respondent_id"] == "R000") & (long_df["task"] == "cj1") & (long_df["profile"] == "A")]
    assert row0.iloc[0]["rol"] == wide_df.iloc[0]["cj1_A_rol"]
    assert row0.iloc[0]["genero"] == wide_df.iloc[0]["cj1_A_gen"]


def test_reshape_summary_counts(wide_df, mapping_config):
    long_df = wide_to_long(wide_df, mapping_config)
    summary = reshape_summary(long_df, mapping_config)
    assert summary["n_respondents"] == len(wide_df)
    assert summary["n_choice_sets"] == len(wide_df) * len(mapping_config.tasks)
    assert summary["choice_sets_without_selection"] == 0
    assert summary["choice_sets_with_multiple_selections"] == 0
    assert "policia" in summary["attribute_coverage"]["rol"]["levels"]


def test_validate_config_no_issues_on_well_formed_mapping(wide_df, mapping_config):
    issues = validate_config(wide_df, mapping_config)
    assert issues == []


def test_validate_config_flags_missing_column(wide_df, mapping_config):
    mapping_config.choice_columns["cj1"] = "columna_inexistente"
    issues = validate_config(wide_df, mapping_config)
    assert any("columna_inexistente" in issue for issue in issues)
