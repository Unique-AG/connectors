# Dogfood administrator runbook

One command enables what the recorder needs in the Dogfood tenant. Run it from
`services/office-365-mcp` as the Dogfood administrator.

```sh
scripts/dogfood/admin/setup.sh [setup|check] [--dry-run] [--yes]
```

- `setup` (default) checks each step and asks before it changes anything. A step that is done is skipped.
- `check` changes nothing. It prints three lines: `done`, `missing`, `needs-human`.
- `--dry-run` prints each write as `WOULD RUN: ...` and runs none. Reads still run.
- `--yes` skips the questions.

The script reads these values from the environment, or from `~/.config/dogfood/env`:

| Name | Meaning |
| --- | --- |
| `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID` | The tenant and the app registration |
| `SEED_UPNS` | The addresses of Mia, Anna and Tom, in this order |
| `SEED_GUEST_INVITE_EMAIL` | A mailbox you control. The guest user gets this address |

It never reads, stores or prints a token. It never prints or stores a password.

## Steps

1. `login`: `az login` to the tenant.
2. `permissions`: add the delegated Graph permissions of `get_token.py --list-scopes` and the
   extra recorder permissions to the app. The extra ones include `Group.Read.All`,
   `Group.ReadWrite.All`, `Channel.Create` and `ChannelMember.ReadWrite.All`.
3. `consent`: add them to the tenant-wide grant (AllPrincipals). The script never removes a scope.
4. `public_client`: set "Allow public client flows" to Yes.
5. `licences`: each tester has Exchange, SharePoint (with OneDrive) and Teams in `assignedPlans`.
   The script assigns no licence.
6. `directory_user`: the user "Anna Brunner" (`seedv1.annabrunner@<domain of Mia>`) with job title,
   department and phones. She has no mailbox licence. The step makes her with `az ad user create`,
   a random password and "change password at next sign-in". Then it sets `accountEnabled` to false.
   Nobody can sign in as her.
7. `guest_user`: the B2B guest "Gast Weber", invited with `sendInvitationMessage` false, so no mail
   goes out. The user has `employeeType` `seed-v1`.
8. `meeting_policy`: the policy `seed-v1 recording` (cloud recording and transcription on), granted
   to Mia, Anna and Tom. Needs `pwsh`. The Teams sign-in uses a device code.
9. `room_mailbox`: the room `seed-v1 room` with auto-accept, capacity 8. Needs `pwsh`. The
   tenant mailbox region does not allow `Set-Place`, so the room has no building or floor.
10. `shared_mailbox`: the shared mailbox `seed-v1 shared` with FullAccess (no automapping) and
    SendAs for Mia. Needs `pwsh`.
11. `room_visible`: the room appears in `/places/microsoft.graph.room`. No command can force this.
12. `seed_env`: write four values to `~/.config/dogfood/env` (mode 600). They are no secrets.
    Other lines stay as they are. The step runs only when all earlier steps that it can change
    are done.

| Value | Content |
| --- | --- |
| `SEED_DIRECTORY_UPN` | Address of Anna Brunner |
| `SEED_GUEST_UPN` | The mail address of the guest, equal to `SEED_GUEST_INVITE_EMAIL` |
| `SEED_ROOM_UPN` | `seedv1room@<domain of Mia>` |
| `SEED_SHARED_UPN` | `seedv1shared@<domain of Mia>` |

The address of the guest is its mail address, not the `#EXT#` sign-in name. Calendar tools need
the mail address. The `az` token needs `User.ReadWrite.All` and `User.Invite.All`. A Global
Administrator who signs in with `az` has this access. The app does not need them.

The password goes to one `az` process as an argument. The script shows it as `<hidden>`.

## What only the administrator does

- Run `az login` as a Global Administrator, and enter the device codes of Teams and Exchange.
  Each `pwsh` step asks for one device code per check and per change.
- Assign the licences if `licences` is `needs-human`.
- Wait. A meeting policy grant can take 24 hours. A new room can take one hour to show in Graph.
  A new mailbox permission can take some minutes.
- After step 3, each tester runs `record_all.sh login` again, because a cached sign-in does not hold a new scope.
- If `room_visible` stays `needs-human`, run `record_all.sh discover`. The `az` token can lack Place.Read.All.

Tests: `pytest scripts/dogfood/admin -q -p no:cacheprovider`. They run `setup.sh --dry-run` with stub commands.
