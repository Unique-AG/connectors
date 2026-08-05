from __future__ import annotations

from datetime import UTC, datetime

from fastmcp import FastMCPApp
from fastmcp.dependencies import Depends
from prefab_ui import PrefabApp
from prefab_ui.actions import SetState, ShowToast
from prefab_ui.actions.mcp import CallTool
from prefab_ui.components import (
    RESULT,
    Alert,
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
    Text,
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
from q_bridge_mcp.skills.service import (
    CatalogPrewarmer,
    get_skill_catalog_service,
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
    catalog_prewarmer: CatalogPrewarmer = Depends(  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
        get_skill_catalog_service
    ),
) -> dict[str, str]:
    """Save the authenticated user's skills root folder."""
    profile = UserProfile(skillsRootFolder=skills_root_folder)
    await repository.save(
        company_id=company_id,
        user_id=user_id,
        profile=profile,
    )
    _ = await catalog_prewarmer.prewarm(user_id=user_id, company_id=company_id)
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
    catalog_prewarmer: CatalogPrewarmer = Depends(  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
        get_skill_catalog_service
    ),
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
    _ = await catalog_prewarmer.prewarm(user_id=user_id, company_id=company_id)
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
                on_submit=[
                    SetState("profileStatus", "Saving profile…"),
                    SetState("profileStatusVariant", "info"),
                    CallTool(
                        save_profile,
                        arguments={
                            "skills_root_folder": Rx("skills_root_folder"),
                        },
                        on_success=[
                            SetState(
                                "skills_root_folder",
                                RESULT.skillsRootFolder,
                            ),
                            SetState(
                                "profileStatus",
                                "Profile saved successfully",
                            ),
                            SetState("profileStatusVariant", "success"),
                            ShowToast("Profile saved", variant="success"),
                        ],
                        on_error=[
                            SetState("profileStatus", "Unable to save profile"),
                            SetState("profileStatusVariant", "destructive"),
                            ShowToast(
                                "Unable to save profile",
                                variant="error",
                            ),
                        ],
                    ),
                ]
            ):
                with CardContent():
                    with Field():
                        _ = FieldTitle("Skills root folder")
                        _ = Input(
                            name="skills_root_folder",
                            value=Rx("skills_root_folder"),
                            placeholder="Skills",
                            required=True,
                            max_length=255,
                        )
                        _ = FieldDescription(
                            "Enter a folder name, not a path or Unique scope ID."
                        )
                    with Alert(variant=Rx("profileStatusVariant")):
                        _ = Text(content=Rx("profileStatus"))
                with CardFooter():
                    _ = Button("Save profile", buttonType="submit")

        with Card():
            with CardHeader():
                _ = CardTitle("Organization app")
                _ = CardDescription(
                    "Configure the dedicated Unique app shared by this organization."
                )
            with Form(
                on_submit=[
                    SetState(
                        "organizationStatus",
                        "Validating organization credentials…",
                    ),
                    SetState("organizationStatusVariant", "info"),
                    CallTool(
                        save_organization_credentials,
                        arguments={
                            "api_key": Rx("api_key"),
                            "app_id": Rx("app_id"),
                        },
                        on_success=[
                            SetState("app_id", RESULT.appId),
                            SetState("api_key", ""),
                            SetState("apiKeyHint", RESULT.apiKeyHint),
                            SetState(
                                "organizationConfigured",
                                RESULT.organizationConfigured,
                            ),
                            SetState(
                                "organizationStatus",
                                "Organization credentials saved successfully",
                            ),
                            SetState(
                                "organizationStatusVariant",
                                "success",
                            ),
                            ShowToast(
                                "Organization credentials saved",
                                variant="success",
                            ),
                        ],
                        on_error=[
                            SetState(
                                "organizationStatus",
                                "Unable to validate organization credentials",
                            ),
                            SetState(
                                "organizationStatusVariant",
                                "destructive",
                            ),
                            ShowToast(
                                "Unable to validate organization credentials",
                                variant="error",
                            ),
                        ],
                    ),
                ]
            ):
                with CardContent():
                    with Field():
                        _ = FieldTitle("App ID")
                        _ = Input(
                            name="app_id",
                            value=Rx("app_id"),
                            required=True,
                            max_length=255,
                        )
                        _ = FieldTitle("API key")
                        _ = Input(
                            name="api_key",
                            value=Rx("api_key"),
                            input_type="password",
                            placeholder="Enter a new API key",
                            required=True,
                        )
                        _ = FieldDescription(
                            "The key is validated, encrypted at rest, and never returned."
                        )
                    with Alert(variant=Rx("organizationStatusVariant")):
                        _ = Text(content=Rx("organizationStatus"))
                with CardFooter():
                    _ = Button("Save organization app", buttonType="submit")

    return PrefabApp(
        title="Q Bridge profile settings",
        view=view,
        state={
            "api_key": "",
            "apiKeyHint": credentials.api_key_hint if credentials is not None else "",
            "app_id": credentials.app_id if credentials is not None else "",
            "organizationStatus": (
                "Organization app configured"
                if credentials is not None
                else "Organization app not configured"
            ),
            "organizationStatusVariant": (
                "success" if credentials is not None else "warning"
            ),
            "organizationConfigured": credentials is not None,
            "profileStatus": (
                "Profile configured"
                if profile.skills_root_folder is not None
                else "Profile not configured"
            ),
            "profileStatusVariant": (
                "success" if profile.skills_root_folder is not None else "warning"
            ),
            "skills_root_folder": profile.skills_root_folder or "",
        },
    )
