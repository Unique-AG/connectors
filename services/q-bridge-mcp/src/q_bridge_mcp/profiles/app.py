from __future__ import annotations

from datetime import UTC, datetime

from fastmcp import FastMCPApp
from fastmcp.dependencies import Depends
from prefab_ui import PrefabApp
from prefab_ui.actions import SetState, ShowToast
from prefab_ui.actions.mcp import CallTool
from prefab_ui.components import (
    RESULT,
    Button,
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
    Column,
    Field,
    FieldDescription,
    FieldTitle,
    Form,
    Input,
)
from prefab_ui.rx import Rx

from q_bridge_mcp.dependencies import get_company_id, get_user_id
from q_bridge_mcp.profiles.models import OrganizationCredentials, UserProfile
from q_bridge_mcp.profiles.repository import (
    OrganizationCredentialsRepository,
    UserProfileRepository,
    get_organization_credentials_repository,
    get_profile_repository,
)
from q_bridge_mcp.profiles.validation import (
    CredentialsValidator,
    get_credentials_validator,
)

profile_app = FastMCPApp("user-profile")


@profile_app.tool()
async def save_profile(
    skills_root_folder: str,
    repository: UserProfileRepository = Depends(  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
        get_profile_repository
    ),
    user_id: str = Depends(get_user_id),  # pyright: ignore[reportCallInDefaultInitializer]
    company_id: str = Depends(get_company_id),  # pyright: ignore[reportCallInDefaultInitializer]
) -> dict[str, str]:
    """Save the authenticated user's skills root folder."""
    profile = UserProfile(skillsRootFolder=skills_root_folder)
    await repository.save(
        company_id=company_id,
        user_id=user_id,
        profile=profile,
    )
    return profile.model_dump(by_alias=True, exclude_none=True)


@profile_app.tool()
async def save_organization_credentials(
    app_id: str,
    api_key: str,
    repository: OrganizationCredentialsRepository = Depends(  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
        get_organization_credentials_repository
    ),
    validator: CredentialsValidator = Depends(  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
        get_credentials_validator
    ),
    user_id: str = Depends(get_user_id),  # pyright: ignore[reportCallInDefaultInitializer]
    company_id: str = Depends(get_company_id),  # pyright: ignore[reportCallInDefaultInitializer]
) -> dict[str, str | bool]:
    """Validate and save the authenticated organization's app credentials."""
    credentials = OrganizationCredentials(
        appId=app_id,
        apiKey=api_key,
        configuredBy=user_id,
        updatedAt=datetime.now(UTC),
    )
    await validator.validate(
        credentials=credentials,
        user_id=user_id,
        company_id=company_id,
    )
    await repository.save(company_id=company_id, credentials=credentials)
    return {
        "appId": credentials.app_id,
        "apiKeyHint": credentials.api_key_hint,
        "organizationConfigured": True,
    }


@profile_app.ui(
    name="profile_settings",
    title="Q Bridge profile settings",
    description=(
        "Open Q Bridge settings to configure the user profile and organization app."
    ),
)
async def profile_settings(
    profile_repository: UserProfileRepository = Depends(  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
        get_profile_repository
    ),
    credentials_repository: OrganizationCredentialsRepository = Depends(  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
        get_organization_credentials_repository
    ),
    user_id: str = Depends(get_user_id),  # pyright: ignore[reportCallInDefaultInitializer]
    company_id: str = Depends(get_company_id),  # pyright: ignore[reportCallInDefaultInitializer]
) -> PrefabApp:
    """Open the authenticated user's Q Bridge profile settings."""
    profile = await profile_repository.get(company_id=company_id, user_id=user_id)
    credentials = await credentials_repository.get(company_id=company_id)

    with Column(gap=6, css_class="w-full max-w-xl") as view:
        with Card():
            with CardHeader():
                _ = CardTitle("User profile")
                _ = CardDescription(
                    "Choose the Unique folder containing the skills available to you."
                )
            with Form(
                on_submit=CallTool(
                    save_profile,
                    on_success=[
                        SetState("skillsRootFolder", RESULT.skillsRootFolder),
                        ShowToast("Profile saved", variant="success"),
                    ],
                    on_error=ShowToast("Unable to save profile", variant="error"),
                )
            ):
                with CardContent(), Field():
                    _ = FieldTitle("Skills root folder")
                    _ = Input(
                        name="skills_root_folder",
                        value=Rx("skillsRootFolder"),
                        placeholder="Skills",
                        required=True,
                        max_length=255,
                    )
                    _ = FieldDescription(
                        "Enter a folder name, not a path or Unique scope ID."
                    )
                with CardFooter():
                    _ = Button("Save profile", buttonType="submit")

        with Card():
            with CardHeader():
                _ = CardTitle("Organization app")
                _ = CardDescription(
                    "Configure the dedicated Unique app shared by this organization."
                )
            with Form(
                on_submit=CallTool(
                    save_organization_credentials,
                    on_success=[
                        SetState("organizationAppId", RESULT.appId),
                        SetState("apiKeyHint", RESULT.apiKeyHint),
                        SetState(
                            "organizationConfigured",
                            RESULT.organizationConfigured,
                        ),
                        ShowToast(
                            "Organization credentials saved",
                            variant="success",
                        ),
                    ],
                    on_error=ShowToast(
                        "Unable to validate organization credentials",
                        variant="error",
                    ),
                )
            ):
                with CardContent(), Field():
                    _ = FieldTitle("App ID")
                    _ = Input(
                        name="app_id",
                        value=Rx("organizationAppId"),
                        required=True,
                        max_length=255,
                    )
                    _ = FieldTitle("API key")
                    _ = Input(
                        name="api_key",
                        input_type="password",
                        placeholder="Enter a new API key",
                        required=True,
                    )
                    _ = FieldDescription(
                        "The key is validated, encrypted at rest, and never returned."
                    )
                with CardFooter():
                    _ = Button("Save organization app", buttonType="submit")

    return PrefabApp(
        title="Q Bridge profile settings",
        view=view,
        state={
            "apiKeyHint": credentials.api_key_hint if credentials is not None else "",
            "organizationAppId": credentials.app_id if credentials is not None else "",
            "organizationConfigured": credentials is not None,
            "skillsRootFolder": profile.skills_root_folder or "",
        },
    )
