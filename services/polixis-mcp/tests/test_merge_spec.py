from spec.merge_spec import merged_yaml
from spec.merge_spec import OUT


def test_openapi_yml_is_what_the_merge_builds() -> None:
    assert OUT.read_text() == merged_yaml(), (
        "upstream/openapi.yml differs from what spec/merge_spec.py builds. Never edit it by "
        "hand: add an edit to merge_spec.py and run `uv run poe merge-spec`."
    )
