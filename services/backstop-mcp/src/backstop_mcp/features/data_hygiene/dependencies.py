from functools import lru_cache

from backstop_mcp.dependencies import get_backstop_config
from backstop_mcp.features.data_hygiene.employment_index_factory import EmploymentIndexFactory
from backstop_mcp.features.data_hygiene.internal_dto import EmploymentRulesDto


@lru_cache(maxsize=1)
def get_employment_rules() -> EmploymentRulesDto:
    """The process-wide employment vocabulary. Shared by the index and the type catalog."""
    config = get_backstop_config()
    return EmploymentRulesDto.from_vocabulary(
        employment_type_ids=config.employment_relationship_type_ids,
        employment_type_markers=config.employment_relationship_type_markers,
        former_type_ids=config.former_employment_relationship_type_ids,
        former_type_markers=config.former_employment_relationship_type_markers,
    )


@lru_cache(maxsize=1)
def get_employment_index_factory() -> EmploymentIndexFactory:
    return EmploymentIndexFactory(rules=get_employment_rules())
