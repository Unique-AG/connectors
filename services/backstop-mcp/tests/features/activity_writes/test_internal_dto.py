from backstop_mcp.features.activity_writes import AuthorDto
from backstop_mcp.features.system_users import SystemUserDto


def test_from_system_user_copies_id_login_and_name() -> None:
    user = SystemUserDto(id="su-author", user_name="bob.smith", name="Bob Smith")

    author = AuthorDto.from_system_user(user)

    assert author == AuthorDto(id="su-author", user_name="bob.smith", name="Bob Smith")
