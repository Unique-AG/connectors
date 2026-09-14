import pytest

from backstop_mcp.features.entity_types import SearchType, map_search_type_to_resource_type_bean


@pytest.mark.parametrize(
    ("search_type", "bean"),
    [
        ("organizations", "OrganizationBean"),
        ("people", "PersonBean"),
        ("contacts", "ContactBean"),
        ("employees", "EmployeeBean"),
    ],
)
def test_map_search_type_to_resource_type_bean(search_type: SearchType, bean: str) -> None:
    assert map_search_type_to_resource_type_bean(search_type) == bean
