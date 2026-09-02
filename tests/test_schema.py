from litellm_codex_models.schema import parse_model_info_schema


def test_parse_model_info_schema_required_and_defaulted_fields():
    source = r'''
pub struct SomethingElse {
    pub ignored: String,
}

pub struct ModelInfo {
    pub slug: String,
    pub description: Option<String>,
    #[serde(default)]
    pub feature_flag: bool,
    #[serde(
        default = "default_value",
        skip_serializing_if = "is_default"
    )]
    pub percentage: i64,
    #[serde(default, skip_serializing, skip_deserializing)]
    pub internal_only: bool,
    pub new_required: Vec<String>,
}
'''
    schema = parse_model_info_schema(source)
    assert schema.fields == {
        "slug",
        "description",
        "feature_flag",
        "percentage",
        "internal_only",
        "new_required",
    }
    assert schema.required_fields == {"slug", "new_required"}
