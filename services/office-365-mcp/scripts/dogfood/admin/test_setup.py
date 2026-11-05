import re
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

Run = Callable[..., tuple[subprocess.CompletedProcess[str], list[str]]]
SETUP = Path(__file__).parent / "setup.sh"
TENANT = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
GRAPH = "00000003-0000-0000-c000-000000000000"
STEPS = [
    "login",
    "permissions",
    "consent",
    "public_client",
    "licences",
    "directory_user",
    "guest_user",
    "meeting_policy",
    "room_mailbox",
    "shared_mailbox",
    "room_visible",
    "seed_env",
]
GUEST = "guest.inbox@dogfood.test"
SEEDED = "\n".join(
    [
        "SEED_DIRECTORY_UPN=seedv1.annabrunner@dogfood.test",
        f"SEED_GUEST_UPN={GUEST}",
        "SEED_ROOM_UPN=seedv1room@dogfood.test",
        "SEED_SHARED_UPN=seedv1shared@dogfood.test",
        "",
    ]
)
FROM_RECORDER = ["User.Read", "Chat.ReadWrite", "Mail.Read"]
EXTRAS = [
    "Place.Read.All",
    "Group.Read.All",
    "Group.ReadWrite.All",
    "Channel.Create",
    "ChannelMember.ReadWrite.All",
    "Notes.ReadWrite.All",
    "Team.Create",
    "TeamMember.ReadWriteNonOwnerRole.All",
    "OnlineMeetings.ReadWrite",
    "OnlineMeetingTranscript.Read.All",
    "OnlineMeetingRecording.Read.All",
    "Calendars.Read.Shared",
    "Mail.ReadWrite.Shared",
    "Sites.ReadWrite.All",
    "Files.ReadWrite.All",
    "ChannelMessage.Send",
    "User.ReadBasic.All",
]
PREFIXES = (
    "az login",
    "az ad app permission add",
    "az ad sp create",
    "az rest --method POST",
    "az ad app update",
    "az ad user create",
    "az rest --method PATCH",
    "az rest --method POST",
    "az rest --method PATCH",
    "pwsh -NoProfile -File",
    "pwsh -NoProfile -File",
    "pwsh -NoProfile -File",
    "mkdir -p",
    "install -m 600",
)
WRITES = (
    "login",
    "permission add",
    "sp create",
    "--method POST",
    "--method PATCH",
    "app update",
    "user create",
)

AZ = f"""#!/bin/bash
echo "az $*" >> "$STUB_LOG"
fresh=$([ "$STUB_STATE" = fresh ] && echo 1)
case "$*" in
  "account show"*) [ -z "$fresh" ] && echo {TENANT} || exit 1 ;;
  *oauth2PermissionScopes*) printf '%s\\n' "$STUB_MAP" ;;
  "ad sp show --id {GRAPH}"*) echo graph-sp ;;
  "ad sp show --id {CLIENT}"*) [ -z "$fresh" ] && echo app-sp ;;
  *requiredResourceAccess*) [ -z "$fresh" ] && printf '%s\\n' "$STUB_IDS" ;;
  *"mail eq"*"value[0].id"*) echo guest-1 ;;
  *"mail eq"*) [ -z "$fresh" ] && echo seed-v1 ;;
  *annabrunner*"join("*) [ -z "$fresh" ] && echo "Facilities Lead|seed-v1|+41 79 555 01 05|+41 44 555 01 04|false" ;;
  *annabrunner*"--query id"*) [ -z "$fresh" ] && echo user-1 ;;
  *assignedPlans*) [ -z "$fresh" ] && printf 'exchange\\nSharePoint\\nTeamspaceAPI\\n' ;;
  *isFallbackPublicClient*) [ -z "$fresh" ] && echo True || echo False ;;
  *"value[0].id"*) [ -z "$fresh" ] && echo grant-1 ;;
  *"value[0].scope"*) [ -z "$fresh" ] && echo "$STUB_SCOPES" ;;
  *places*) [ -z "$fresh" ] && echo 1 || echo 0 ;;
esac
exit 0
"""
UV = '#!/bin/bash\necho "uv $*" >> "$STUB_LOG"\nprintf \'https://graph.microsoft.com/%s\\n\' $STUB_RECORDER\n'
PWSH = (
    '#!/bin/bash\necho "pwsh $*" >> "$STUB_LOG"\n[ "$STUB_STATE" = fresh ] && echo no || echo yes\n'
)


@pytest.fixture
def run(tmp_path: Path) -> Run:
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name, body in {"az": AZ, "uv": UV, "pwsh": PWSH}.items():
        (stubs / name).write_text(body)
        (stubs / name).chmod(0o755)
    names = FROM_RECORDER + EXTRAS
    log = tmp_path / "log"
    home = tmp_path / "home"
    (home / ".config/dogfood").mkdir(parents=True)

    def invoke(
        *args: str, state: str = "fresh", env_file: bool = True, seeded: bool = False
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        if env_file:
            lines = [
                f"ENTRA_TENANT_ID={TENANT}",
                f"export ENTRA_CLIENT_ID={CLIENT}",
                "SEED_UPNS=mia@dogfood.test,anna@dogfood.test,tom@dogfood.test",
                f"SEED_GUEST_INVITE_EMAIL={GUEST}",
            ]
            (home / ".config/dogfood/env").write_text(
                "\n".join(lines) + "\n" + (SEEDED if seeded else "")
            )
        env = {
            "PATH": f"{stubs}:/usr/bin:/bin",
            "HOME": str(home),
            "STUB_LOG": str(log),
            "STUB_STATE": state,
            "STUB_RECORDER": " ".join(FROM_RECORDER),
            "STUB_MAP": "\n".join(f"{n}\tid-{n}" for n in names),
            "STUB_IDS": "\n".join(f"id-{n}" for n in names),
            "STUB_SCOPES": " ".join(names),
        }
        done = subprocess.run(
            ["bash", str(SETUP), *args], env=env, text=True, capture_output=True, check=False
        )
        return done, (log.read_text().splitlines() if log.exists() else [])

    return invoke


def passwords(text: str) -> list[str]:
    found: list[str] = re.findall(r"--password (\S+)", text)
    return found


def would_run(stdout: str) -> list[str]:
    return [
        line.removeprefix("WOULD RUN: ")
        for line in stdout.splitlines()
        if line.startswith("WOULD RUN: ")
    ]


def test_dry_run_lists_every_write_in_order(run: Run) -> None:
    done, _ = run("--dry-run")
    commands = would_run(done.stdout)
    assert [c.startswith(p) for c, p in zip(commands, PREFIXES, strict=True)] == [True] * len(
        PREFIXES
    )
    assert (
        "meeting_policy.ps1 apply mia@dogfood.test,anna@dogfood.test,tom@dogfood.test"
        in commands[9]
    )
    assert commands[10].endswith("room.ps1 apply seedv1room@dogfood.test")
    assert commands[11].endswith("shared.ps1 apply seedv1shared@dogfood.test mia@dogfood.test")


def test_dry_run_changes_nothing(run: Run) -> None:
    done, log = run("--dry-run")
    assert not [line for line in log for write in WRITES if write in line]
    assert all(" check" in line for line in log if line.startswith("pwsh"))
    assert "get-access-token" not in done.stdout + "".join(log)


def test_permission_add_holds_the_union_once(run: Run) -> None:
    done, _ = run("--dry-run")
    add = next(c for c in would_run(done.stdout) if "permission add" in c)
    ids = add.split("--api-permissions ")[1].split()
    assert sorted(ids) == sorted(f"id-{n}=Scope" for n in FROM_RECORDER + EXTRAS)
    assert f"--api {GRAPH}" in add


def test_consent_posts_all_principals_grant(run: Run) -> None:
    done, _ = run("--dry-run")
    post = next(c for c in would_run(done.stdout) if "--method POST" in c)
    assert "oauth2PermissionGrants" in post
    assert "AllPrincipals" in post
    assert "Team.Create" in post


def test_finished_tenant_needs_no_change(run: Run) -> None:
    done, log = run("--dry-run", state="done", seeded=True)
    assert would_run(done.stdout) == []
    assert f"done: {' '.join(STEPS)}\n" in done.stdout
    assert "missing: \n" in done.stdout
    assert "az login" not in "".join(log)


def test_check_prints_three_lines_and_changes_nothing(run: Run) -> None:
    done, log = run("check")
    assert [line.split(":")[0] for line in done.stdout.splitlines()[-3:]] == [
        "done",
        "missing",
        "needs-human",
    ]
    assert done.returncode == 1
    assert "WOULD RUN" not in done.stdout
    assert not [line for line in log for write in WRITES if write in line]
    assert "needs-human: licences room_visible seed_env" in done.stdout


def test_ids_come_from_env_file_and_are_checked(run: Run) -> None:
    done, _ = run("--dry-run", env_file=False)
    assert done.returncode == 1
    assert "ENTRA_TENANT_ID" in done.stderr


def test_unknown_argument_is_refused(run: Run) -> None:
    done, _ = run("--wipe")
    assert done.returncode == 2
    assert "Usage" in done.stderr


def test_directory_user_has_no_licence_and_cannot_sign_in(run: Run) -> None:
    done, _ = run("--dry-run")
    commands = would_run(done.stdout)
    assert "--display-name Anna Brunner" in commands[5]
    assert "--user-principal-name seedv1.annabrunner@dogfood.test" in commands[5]
    assert "--force-change-password-next-sign-in true" in commands[5]
    assert "--password <hidden>" in commands[5]
    for part in (
        '"accountEnabled":false',
        "Facilities Lead",
        "+41 79 555 01 05",
        "+41 44 555 01 04",
    ):
        assert part in commands[6]


def test_password_is_random_and_never_printed_or_stored(run: Run, tmp_path: Path) -> None:
    done, log = run("--yes")
    [secret] = passwords("\n".join(log))
    assert len(secret) >= 24
    env_file = (tmp_path / "home/.config/dogfood/env").read_text()
    assert secret not in done.stdout + done.stderr + env_file
    again, log_again = run("--yes")
    secrets = passwords("\n".join(log_again))
    assert len(set(secrets)) == 2
    assert not [found for found in secrets if found in again.stdout + again.stderr]


def test_directory_user_that_exists_is_not_created_again(run: Run) -> None:
    done, log = run("--dry-run", state="done", seeded=True)
    assert "user create" not in "".join(log)
    assert would_run(done.stdout) == []


def test_guest_is_invited_without_mail_and_tagged(run: Run) -> None:
    done, _ = run("--dry-run")
    commands = would_run(done.stdout)
    assert f'"invitedUserEmailAddress":"{GUEST}"' in commands[7]
    assert '"sendInvitationMessage":false' in commands[7]
    assert '"invitedUserDisplayName":"Gast Weber"' in commands[7]
    assert commands[8].startswith(
        "az rest --method PATCH --url https://graph.microsoft.com/v1.0/users/guest-1"
    )
    assert '"employeeType":"seed-v1"' in commands[8]


def test_missing_guest_address_is_refused(run: Run, tmp_path: Path) -> None:
    run("--dry-run")
    env = tmp_path / "home/.config/dogfood/env"
    env.write_text(env.read_text().replace(f"SEED_GUEST_INVITE_EMAIL={GUEST}\n", ""))
    done, _ = run("--dry-run", env_file=False)
    assert done.returncode == 1
    assert "SEED_GUEST_INVITE_EMAIL" in done.stderr


def test_missing_licence_needs_a_human(run: Run) -> None:
    done, _ = run("check")
    assert "mia@dogfood.test lacks: exchange SharePoint TeamspaceAPI" in done.stderr
    assert "tom@dogfood.test lacks:" in done.stderr
    assert "licences" in done.stdout.splitlines()[-1]


def test_seed_values_are_written_once_with_mode_600(run: Run, tmp_path: Path) -> None:
    env = tmp_path / "home/.config/dogfood/env"
    done, _ = run("--yes", state="done")
    assert done.returncode == 0
    text = env.read_text()
    for line in SEEDED.splitlines():
        assert text.count(line) == 1
    assert f"ENTRA_TENANT_ID={TENANT}" in text
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    before = text
    again, _ = run("--yes", state="done", env_file=False)
    assert "install" not in again.stdout
    assert env.read_text() == before


def test_stale_seed_value_is_replaced_not_duplicated(run: Run, tmp_path: Path) -> None:
    run("--dry-run", state="done", seeded=True)
    env = tmp_path / "home/.config/dogfood/env"
    env.write_text(env.read_text().replace("seedv1room@", "old.room@"))
    done, _ = run("--yes", state="done", env_file=False)
    assert done.returncode == 0
    assert env.read_text().count("SEED_ROOM_UPN=") == 1
    assert "SEED_ROOM_UPN=seedv1room@dogfood.test" in env.read_text()


def test_seed_values_wait_for_the_earlier_steps(run: Run) -> None:
    done, _ = run("--yes")
    assert "install" not in done.stdout
    assert "needs-human:" in done.stdout
    assert "seed_env" in done.stdout.splitlines()[-1]
