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


def test_parse_model_info_schema_multiline_and_restricted_visibility_fields():
    source = r'''
pub struct ModelInfo {
    pub slug: String,
    pub(crate) wrapped_required:
        std::collections::BTreeMap<
            String,
            Vec<String>,
        >,
    #[serde(default)]
    private_defaulted:
        std::collections::BTreeMap<
            String,
            Vec<String>,
        >,
    private_optional:
        Option<
            String,
        >,
}
'''
    schema = parse_model_info_schema(source)
    assert schema.fields == {
        "slug",
        "wrapped_required",
        "private_defaulted",
        "private_optional",
    }
    assert schema.required_fields == {"slug", "wrapped_required"}


def test_parse_model_info_schema_rejects_unterminated_multiline_field():
    source = r'''
pub struct ModelInfo {
    pub slug: String,
    pub broken:
        Vec<
            String,
}
'''
    try:
        parse_model_info_schema(source)
    except Exception as exc:
        assert "Unterminated field declaration" in str(exc)
    else:
        raise AssertionError("expected unterminated field declaration to fail closed")
