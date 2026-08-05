import asyncio
from datetime import UTC, datetime

import pytest
from key_value.aio.stores.memory import MemoryStore
from prefab_ui.app import ResolvedTool

from q_bridge_mcp.profiles.app import (
    profile_settings,
    save_organization_credentials,
    save_profile,
)
from q_bridge_mcp.profiles.dependencies import (
    ConfigurationRequiredError,
    require_configuration,
)
from q_bridge_mcp.profiles.models import OrganizationCredentials, UserProfile
from q_bridge_mcp.profiles.repository import (
    ORGANIZATION_CREDENTIALS_COLLECTION,
    PROFILE_COLLECTION,
    OrganizationCredentialsRepository,
    UserProfileRepository,
)


class AcceptingCredentialsValidator:
    def __init__(self) -> None:
        self.validated_credentials: OrganizationCredentials | None = None
        self.validated_user_id: str | None = None
        self.validated_company_id: str | None = None

    async def validate(
        self,
        *,
        credentials: OrganizationCredentials,
        user_id: str,
        company_id: str,
    ) -> None:
        self.validated_credentials = credentials
        self.validated_user_id = user_id
        self.validated_company_id = company_id


class RecordingCatalogPrewarmer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def prewarm(self, *, user_id: str, company_id: str) -> bool:
        self.calls.append((user_id, company_id))
        return True


def get_form_tool_action(
    component: dict[str, object],
    tool_name: str,
) -> dict[str, object] | None:
    action = component.get("onSubmit")
    if isinstance(action, dict) and action.get("tool") == tool_name:
        return action
    if isinstance(action, list):
        for item in action:
            if isinstance(item, dict) and item.get("tool") == tool_name:
                return item

    children = component.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                tool_action = get_form_tool_action(child, tool_name)
                if tool_action is not None:
                    return tool_action

    return None


def get_state_update(actions: object, key: str) -> object:
    if isinstance(actions, list):
        for action in actions:
            if (
                isinstance(action, dict)
                and action.get("action") == "setState"
                and action.get("key") == key
            ):
                return action.get("value")
    return None


@pytest.mark.ai
def test_user_profile__serializes_only_skills_root_folder() -> None:
    """Purpose: Verify the initial profile schema contains only the skills root.
    Why this matters: The first profile version must stay intentionally minimal.
    Setup summary: Build a profile and assert its persisted JSON representation.
    """
    profile = UserProfile(skillsRootFolder="Company Skills")

    assert profile.model_dump(by_alias=True) == {
        "skillsRootFolder": "Company Skills",
    }


@pytest.mark.ai
@pytest.mark.parametrize("folder_name", ["skills-conduct", "/skills-conduct"])
def test_user_profile__accepts_folder_names_with_optional_leading_slash(
    folder_name: str,
) -> None:
    """Purpose: Verify folder names work with or without a leading slash.
    Why this matters: Unique folder references are commonly entered in both formats.
    Setup summary: Validate both supported forms and assert the value is preserved.
    """
    profile = UserProfile(skillsRootFolder=folder_name)

    assert profile.skills_root_folder == folder_name


@pytest.mark.ai
def test_repository__returns_unconfigured_profile_when_missing() -> None:
    """Purpose: Verify first-time users receive an empty profile.
    Why this matters: Opening settings must work before any profile is saved.
    Setup summary: Read from an empty in-memory store and assert the default.
    """
    repository = UserProfileRepository(MemoryStore())

    profile = asyncio.run(repository.get(company_id="company-1", user_id="user-1"))

    assert profile.skills_root_folder is None


@pytest.mark.ai
def test_repository__isolates_profiles_by_company_and_user() -> None:
    """Purpose: Verify one authenticated identity cannot overwrite another profile.
    Why this matters: Profile state is tenant- and user-confidential.
    Setup summary: Save one profile and read it using two different identities.
    """
    store = MemoryStore()
    repository = UserProfileRepository(store)
    saved_profile = UserProfile(skillsRootFolder="Legal Skills")

    asyncio.run(
        repository.save(
            company_id="company-1",
            user_id="user-1",
            profile=saved_profile,
        )
    )

    own_profile = asyncio.run(
        repository.get(company_id="company-1", user_id="user-1")
    )
    other_profile = asyncio.run(
        repository.get(company_id="company-1", user_id="user-2")
    )
    stored_value = asyncio.run(
        store.get("company-1:user-1", collection=PROFILE_COLLECTION)
    )

    assert own_profile == saved_profile
    assert other_profile.skills_root_folder is None
    assert stored_value == {"skillsRootFolder": "Legal Skills"}


@pytest.mark.ai
def test_organization_repository__shares_credentials_with_company_only() -> None:
    """Purpose: Verify dedicated app credentials are stored per organization.
    Why this matters: All users in one tenant share one app without cross-tenant access.
    Setup summary: Save credentials by company ID and inspect the dedicated collection.
    """
    store = MemoryStore()
    repository = OrganizationCredentialsRepository(store)
    credentials = OrganizationCredentials(
        appId="app-123",
        apiKey="secret-value",
        configuredBy="user-123",
        updatedAt=datetime(2026, 8, 4, tzinfo=UTC),
    )

    asyncio.run(repository.save(company_id="company-456", credentials=credentials))

    assert (
        asyncio.run(repository.get(company_id="company-456")) == credentials
    )
    assert asyncio.run(repository.get(company_id="other-company")) is None
    assert asyncio.run(
        store.get(
            "company-456",
            collection=ORGANIZATION_CREDENTIALS_COLLECTION,
        )
    ) == {
        "appId": "app-123",
        "apiKey": "secret-value",
        "configuredBy": "user-123",
        "updatedAt": "2026-08-04T00:00:00Z",
    }


@pytest.mark.ai
def test_save_profile__uses_injected_identity() -> None:
    """Purpose: Verify the app backend saves against server-injected identity.
    Why this matters: The browser must never select another user's profile key.
    Setup summary: Call the backend with explicit injected values and read it back.
    """
    repository = UserProfileRepository(MemoryStore())
    prewarmer = RecordingCatalogPrewarmer()

    result = asyncio.run(
        save_profile(
            "Engineering Skills",
            repository,
            "user-123",
            "company-456",
            prewarmer,
        )
    )

    assert result == {"skillsRootFolder": "Engineering Skills"}
    assert prewarmer.calls == [("user-123", "company-456")]
    assert (
        asyncio.run(repository.get(company_id="company-456", user_id="user-123"))
        .skills_root_folder
        == "Engineering Skills"
    )


@pytest.mark.ai
def test_save_organization_credentials__validates_before_persisting() -> None:
    """Purpose: Verify organization credentials are validated and tenant-scoped.
    Why this matters: Invalid or cross-tenant credentials must not enter shared storage.
    Setup summary: Save through an accepting validator and inspect the safe response.
    """
    repository = OrganizationCredentialsRepository(MemoryStore())
    validator = AcceptingCredentialsValidator()
    prewarmer = RecordingCatalogPrewarmer()

    result = asyncio.run(
        save_organization_credentials(
            "app-123",
            "very-secret-api-key",
            repository,
            validator,
            "user-123",
            "company-456",
            prewarmer,
        )
    )

    stored_credentials = asyncio.run(repository.get(company_id="company-456"))
    assert validator.validated_credentials == stored_credentials
    assert validator.validated_user_id == "user-123"
    assert validator.validated_company_id == "company-456"
    assert prewarmer.calls == [("user-123", "company-456")]
    assert result == {
        "appId": "app-123",
        "apiKeyHint": "…-key",
        "organizationConfigured": True,
    }
    assert "very-secret-api-key" not in str(result)


@pytest.mark.ai
def test_require_configuration__rejects_incomplete_setup() -> None:
    """Purpose: Verify credential-dependent tools are blocked before setup.
    Why this matters: Hosts cannot bypass required profile configuration.
    Setup summary: Resolve configuration from empty stores and assert guidance.
    """
    profile_repository = UserProfileRepository(MemoryStore())
    credentials_repository = OrganizationCredentialsRepository(MemoryStore())

    with pytest.raises(ConfigurationRequiredError, match="profile_settings"):
        _ = asyncio.run(
            require_configuration(
                profile_repository,
                credentials_repository,
                "user-123",
                "company-456",
            )
        )


@pytest.mark.ai
def test_profile_settings__loads_current_profile_into_app_state() -> None:
    """Purpose: Verify the MCP App opens with the user's persisted value.
    Why this matters: Users need to see their current configuration before editing.
    Setup summary: Seed a profile, open the app, and inspect its initial state.
    """
    repository = UserProfileRepository(MemoryStore())
    asyncio.run(
        repository.save(
            company_id="company-456",
            user_id="user-123",
            profile=UserProfile(skillsRootFolder="Research Skills"),
        )
    )

    credentials_repository = OrganizationCredentialsRepository(MemoryStore())
    asyncio.run(
        credentials_repository.save(
            company_id="company-456",
            credentials=OrganizationCredentials(
                appId="app-123",
                apiKey="very-secret-api-key",
                configuredBy="user-123",
                updatedAt=datetime(2026, 8, 4, tzinfo=UTC),
            ),
        )
    )

    app = asyncio.run(
        profile_settings(
            repository,
            credentials_repository,
            "user-123",
            "company-456",
        )
    )

    assert app.state == {
        "api_key": "",
        "apiKeyHint": "…-key",
        "app_id": "app-123",
        "organizationStatus": "Organization app configured",
        "organizationStatusVariant": "success",
        "organizationConfigured": True,
        "profileStatus": "Profile configured",
        "profileStatusVariant": "success",
        "skills_root_folder": "Research Skills",
    }
    wire = app.to_json(
        tool_resolver=lambda tool: ResolvedTool(name=tool.__name__),
    )
    profile_action = get_form_tool_action(wire["view"], "save_profile")
    organization_action = get_form_tool_action(
        wire["view"],
        "save_organization_credentials",
    )
    assert profile_action is not None
    assert organization_action is not None
    assert profile_action["arguments"] == {
        "skills_root_folder": "{{ skills_root_folder }}"
    }
    assert get_state_update(profile_action["onSuccess"], "profileStatus") == (
        "Profile saved successfully"
    )
    assert organization_action["arguments"] == {
        "api_key": "{{ api_key }}",
        "app_id": "{{ app_id }}",
    }
    assert get_state_update(
        organization_action["onSuccess"],
        "organizationStatus",
    ) == "Organization credentials saved successfully"
