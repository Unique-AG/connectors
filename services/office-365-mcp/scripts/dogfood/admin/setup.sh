#!/usr/bin/env bash
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE/../../.."

GRAPH_APP=00000003-0000-0000-c000-000000000000
GRAPH_URL=https://graph.microsoft.com/v1.0
ROOM_NAME="seed-v1 room"
DIRECTORY_NAME="Anna Brunner"
DIRECTORY_TITLE="Facilities Lead"
DIRECTORY_MOBILE="+41 79 555 01 05"
DIRECTORY_PHONE="+41 44 555 01 04"
GUEST_NAME="Gast Weber"
LICENCE_SERVICES="exchange SharePoint TeamspaceAPI"
SEED_KEYS="SEED_DIRECTORY_UPN SEED_GUEST_UPN SEED_ROOM_UPN SEED_SHARED_UPN"
ENV_FILE=$HOME/.config/dogfood/env
EXTRA_SCOPES="Place.Read.All Group.Read.All Group.ReadWrite.All Channel.Create ChannelMember.ReadWrite.All
Notes.ReadWrite.All Team.Create
TeamMember.ReadWriteNonOwnerRole.All OnlineMeetings.ReadWrite OnlineMeetingTranscript.Read.All
OnlineMeetingRecording.Read.All Calendars.Read.Shared Mail.ReadWrite.Shared Sites.ReadWrite.All
Files.ReadWrite.All Chat.ReadWrite ChannelMessage.Send User.ReadBasic.All"
STEPS="permissions consent public_client licences directory_user guest_user meeting_policy room_mailbox
shared_mailbox room_visible seed_env"

MODE=setup DRY_RUN=0 ASSUME_YES=0 SECRET=""
for arg in "$@"; do
  case $arg in
    setup | check) MODE=$arg ;;
    --dry-run) DRY_RUN=1 ;;
    --yes) ASSUME_YES=1 ;;
    *) echo "Usage: setup.sh [setup|check] [--dry-run] [--yes]" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
fail() { printf '%s\n' "$*" >&2; exit 1; }

ext() {
  local kind=$1
  shift
  if [ "$kind" = write ]; then
    local shown="$*"
    shown=${shown//"$SECRET"/<hidden>}
    if [ "$DRY_RUN" = 1 ]; then say "WOULD RUN: $shown"; return 0; fi
    say "RUN: $shown"
  fi
  "$@"
}

confirm() {
  local answer
  if [ "$ASSUME_YES" = 1 ] || [ "$DRY_RUN" = 1 ]; then return 0; fi
  read -r -p "$1 [Y/n] " answer </dev/tty
  [ "${answer:-y}" != n ]
}

load_env() {
  local file=$ENV_FILE key value
  if [ -r "$file" ]; then
    while IFS='=' read -r key value || [ -n "$key" ]; do
      key=${key#export }
      case $key in
        ENTRA_TENANT_ID | ENTRA_CLIENT_ID | SEED_UPNS | SEED_GUEST_INVITE_EMAIL)
          [ -n "${!key:-}" ] || export "$key=${value//[\"\']/}" ;;
      esac
    done <"$file"
  fi
  local guid='^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$' upn='^[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+$'
  [[ ${ENTRA_TENANT_ID:-} =~ $guid ]] || fail "Set ENTRA_TENANT_ID in ~/.config/dogfood/env."
  [[ ${ENTRA_CLIENT_ID:-} =~ $guid ]] || fail "Set ENTRA_CLIENT_ID in ~/.config/dogfood/env."
  IFS=, read -r MIA ANNA TOM _ <<<"${SEED_UPNS:-}"
  [[ ${MIA:-} =~ $upn && ${ANNA:-} =~ $upn && ${TOM:-} =~ $upn ]] || fail "Set SEED_UPNS (Mia, Anna, Tom) in ~/.config/dogfood/env."
  GUEST=${SEED_GUEST_INVITE_EMAIL:-}
  [[ $GUEST =~ $upn ]] || fail "Set SEED_GUEST_INVITE_EMAIL to a mailbox you control in ~/.config/dogfood/env."
  export SEED_DIRECTORY_UPN=seedv1.annabrunner@${MIA#*@}
  export SEED_GUEST_UPN=$GUEST
  export SEED_ROOM_UPN=seedv1room@${MIA#*@}
  export SEED_SHARED_UPN=seedv1shared@${MIA#*@}
}

load_scopes() {
  WANTED=$({ ext read uv run python scripts/dogfood/get_token.py --list-scopes; printf '%s\n' "$EXTRA_SCOPES" | tr -s ' ' '\n'; } \
    | sed 's#.*/##' | grep . | sort -u)
  SCOPE_MAP=$(ext read az ad sp show --id "$GRAPH_APP" --query 'oauth2PermissionScopes[].[value,id]' -o tsv 2>/dev/null || true)
  [ -n "$SCOPE_MAP" ] || fail "Cannot read the Graph permissions. Run az login for the tenant first."
}

scope_id() {
  local id
  id=$(printf '%s\n' "$SCOPE_MAP" | awk -F'\t' -v name="$1" '$1 == name { print $2 }')
  [ -n "$id" ] || fail "Unknown Graph permission: $1"
  printf '%s\n' "$id"
}

check_login() {
  [ "$(ext read az account show --query tenantId -o tsv 2>/dev/null || true)" = "$ENTRA_TENANT_ID" ]
}
apply_login() { ext write az login --tenant "$ENTRA_TENANT_ID" --allow-no-subscriptions -o none; }

check_permissions() {
  local registered name id
  registered=$(ext read az ad app show --id "$ENTRA_CLIENT_ID" --query \
    "requiredResourceAccess[?resourceAppId=='$GRAPH_APP'].resourceAccess[?type=='Scope'].id | [0]" -o tsv 2>/dev/null || true)
  NEW_IDS=()
  for name in $WANTED; do
    id=$(scope_id "$name")
    printf '%s\n' "$registered" | grep -qx "$id" || NEW_IDS+=("$id=Scope")
  done
  [ ${#NEW_IDS[@]} -eq 0 ]
}
apply_permissions() {
  ext write az ad app permission add --id "$ENTRA_CLIENT_ID" --api "$GRAPH_APP" --api-permissions "${NEW_IDS[@]}"
}

grant_field() {
  ext read az rest --method GET --url "$GRAPH_URL/oauth2PermissionGrants" --url-parameters \
    "\$filter=clientId eq '$APP_SP' and consentType eq 'AllPrincipals' and resourceId eq '$GRAPH_SP'" \
    --query "value[0].$1" -o tsv 2>/dev/null || true
}
check_consent() {
  local name
  APP_SP=$(ext read az ad sp show --id "$ENTRA_CLIENT_ID" --query id -o tsv 2>/dev/null || true)
  GRAPH_SP=$(ext read az ad sp show --id "$GRAPH_APP" --query id -o tsv 2>/dev/null || true)
  GRANT_ID="" GRANT_SCOPE=""
  [ -n "$APP_SP" ] || return 1
  GRANT_ID=$(grant_field id)
  GRANT_SCOPE=$(grant_field scope)
  for name in $WANTED; do
    case " $GRANT_SCOPE " in *" $name "*) ;; *) return 1 ;; esac
  done
}
apply_consent() {
  local all
  if [ -z "$APP_SP" ]; then
    ext write az ad sp create --id "$ENTRA_CLIENT_ID" -o none
    APP_SP=$(ext read az ad sp show --id "$ENTRA_CLIENT_ID" --query id -o tsv 2>/dev/null || echo "<app service principal id>")
  fi
  all=$(printf '%s\n' "${GRANT_SCOPE// /$'\n'}" "$WANTED" | grep . | sort -u | paste -sd' ' -)
  if [ -n "$GRANT_ID" ]; then
    ext write az rest --method PATCH --url "$GRAPH_URL/oauth2PermissionGrants/$GRANT_ID" --body "{\"scope\":\"$all\"}" -o none
  else
    ext write az rest --method POST --url "$GRAPH_URL/oauth2PermissionGrants" -o none --body \
      "{\"clientId\":\"$APP_SP\",\"consentType\":\"AllPrincipals\",\"resourceId\":\"$GRAPH_SP\",\"scope\":\"$all\"}"
  fi
}

check_public_client() {
  [ "$(ext read az ad app show --id "$ENTRA_CLIENT_ID" --query isFallbackPublicClient -o tsv 2>/dev/null | tr '[:upper:]' '[:lower:]')" = true ]
}
apply_public_client() { ext write az ad app update --id "$ENTRA_CLIENT_ID" --is-fallback-public-client true; }

check_licences() {
  local upn services lacking service rc=0
  for upn in $MIA $ANNA $TOM; do
    services=$(ext read az rest --method GET --url "$GRAPH_URL/users/$upn" --url-parameters "\$select=assignedPlans" \
      --query "assignedPlans[?capabilityStatus=='Enabled'].service" -o tsv 2>/dev/null || true)
    lacking=""
    for service in $LICENCE_SERVICES; do
      printf '%s\n' "$services" | grep -qx "$service" || lacking="$lacking $service"
    done
    if [ -n "$lacking" ]; then say "$upn lacks:$lacking" >&2; rc=2; fi
  done
  return $rc
}

check_directory_user() {
  local row
  row=$(ext read az rest --method GET --url "$GRAPH_URL/users/$SEED_DIRECTORY_UPN" --url-parameters \
    "\$select=jobTitle,employeeType,mobilePhone,businessPhones,accountEnabled" --query \
    "join('|',[jobTitle,employeeType,mobilePhone,businessPhones[0],to_string(accountEnabled)])" -o tsv 2>/dev/null || true)
  [ "$row" = "$DIRECTORY_TITLE|seed-v1|$DIRECTORY_MOBILE|$DIRECTORY_PHONE|false" ]
}
apply_directory_user() {
  SECRET="$(openssl rand -base64 24)aA1!"
  if [ -z "$(ext read az rest --method GET --url "$GRAPH_URL/users/$SEED_DIRECTORY_UPN" --query id -o tsv 2>/dev/null || true)" ]; then
    ext write az ad user create --display-name "$DIRECTORY_NAME" --user-principal-name "$SEED_DIRECTORY_UPN" \
      --mail-nickname "${SEED_DIRECTORY_UPN%@*}" --password "$SECRET" --force-change-password-next-sign-in true -o none
  fi
  SECRET=""
  ext write az rest --method PATCH --url "$GRAPH_URL/users/$SEED_DIRECTORY_UPN" -o none --body \
    "{\"accountEnabled\":false,\"jobTitle\":\"$DIRECTORY_TITLE\",\"department\":\"Facilities\",\"employeeType\":\"seed-v1\",\"mobilePhone\":\"$DIRECTORY_MOBILE\",\"businessPhones\":[\"$DIRECTORY_PHONE\"]}"
}

guest_field() {
  ext read az rest --method GET --url "$GRAPH_URL/users" --url-parameters "\$filter=mail eq '$GUEST'" \
    --query "value[0].$1" -o tsv 2>/dev/null || true
}
check_guest_user() { [ "$(guest_field employeeType)" = seed-v1 ]; }
apply_guest_user() {
  local id="" _
  ext write az rest --method POST --url "$GRAPH_URL/invitations" -o none --body \
    "{\"invitedUserEmailAddress\":\"$GUEST\",\"invitedUserDisplayName\":\"$GUEST_NAME\",\"inviteRedirectUrl\":\"https://myapps.microsoft.com\",\"sendInvitationMessage\":false}"
  for _ in 1 2 3 4 5; do
    id=$(guest_field id)
    if [ -n "$id" ] || [ "$DRY_RUN" = 1 ]; then break; fi
    sleep 3
  done
  ext write az rest --method PATCH --url "$GRAPH_URL/users/${id:-<guest id>}" --body '{"employeeType":"seed-v1"}' -o none
}

pwsh_script() { local kind=$1 file=$2; shift 2; ext "$kind" pwsh -NoProfile -File "$HERE/$file" "$@"; }
check_meeting_policy() { [ "$(pwsh_script read meeting_policy.ps1 check "$MIA,$ANNA,$TOM" | tee /dev/stderr | tail -n1)" = yes ]; }
apply_meeting_policy() { pwsh_script write meeting_policy.ps1 apply "$MIA,$ANNA,$TOM"; }
check_room_mailbox() { [ "$(pwsh_script read room.ps1 check "$SEED_ROOM_UPN" | tee /dev/stderr | tail -n1)" = yes ]; }
apply_room_mailbox() { pwsh_script write room.ps1 apply "$SEED_ROOM_UPN"; }
check_shared_mailbox() { [ "$(pwsh_script read shared.ps1 check "$SEED_SHARED_UPN" "$MIA" | tee /dev/stderr | tail -n1)" = yes ]; }
apply_shared_mailbox() { pwsh_script write shared.ps1 apply "$SEED_SHARED_UPN" "$MIA"; }

check_room_visible() {
  local count
  count=$(ext read az rest --method GET --url "$GRAPH_URL/places/microsoft.graph.room" \
    --query "length(value[?displayName=='$ROOM_NAME'])" -o tsv 2>/dev/null || true)
  [[ ${count:-0} =~ ^[0-9]+$ && $count -ge 1 ]] || return 2
}

check_seed_env() {
  local key
  [ "$DRY_RUN" = 1 ] || [ -z "$MISSING" ] || return 2
  for key in $SEED_KEYS; do
    grep -qxF "$key=${!key}" "$ENV_FILE" 2>/dev/null || return 1
  done
}
apply_seed_env() {
  local key tmp
  tmp=$(mktemp)
  grep -vE "^(export )?($(printf '%s' "$SEED_KEYS" | tr ' ' '|'))=" "$ENV_FILE" >"$tmp" 2>/dev/null || true
  for key in $SEED_KEYS; do printf '%s=%s\n' "$key" "${!key}" >>"$tmp"; done
  ext write mkdir -p "$(dirname "$ENV_FILE")"
  ext write install -m 600 "$tmp" "$ENV_FILE"
  rm -f "$tmp"
}

hint() {
  case $1 in
    login) say "Sign in with az login as the Dogfood administrator." ;;
    licences) say "Assign a licence with Exchange Online, SharePoint with OneDrive, and Teams to each tester in the admin centre. This script assigns none." ;;
    guest_user) say "The invitation sends no mail. The guest stays pending, and that is enough for the recorder." ;;
    meeting_policy) say "A policy grant can take up to 24 hours. Then recording and transcripts work for Mia, Anna and Tom." ;;
    shared_mailbox) say "A new permission can take some minutes to reach Mia. Run record_all.sh discover to check." ;;
    seed_env) say "Run setup again when all earlier steps are done. Then the four SEED_* values go into ~/.config/dogfood/env." ;;
    room_visible) say "The room can take one hour to show in Graph. The az token may lack Place.Read.All: run record_all.sh discover to check." ;;
  esac
}

run_step() {
  local step=$1 rc=0
  say "== $step"
  "check_$step" || rc=$?
  if [ $rc -eq 0 ]; then
    say "done before: nothing to change"
  elif [ $rc -eq 1 ] && [ "$MODE" = setup ] && declare -F "apply_$step" >/dev/null && confirm "Apply $step?"; then
    "apply_$step"
    if [ "$DRY_RUN" = 1 ]; then
      rc=1
    else
      rc=0
      "check_$step" || rc=$?
    fi
    if [ $rc -eq 0 ]; then say "changed: $step"; fi
  fi
  case $rc in
    0) DONE="$DONE $step" ;;
    1) MISSING="$MISSING $step"; hint "$step" ;;
    *) HUMAN="$HUMAN $step"; hint "$step" ;;
  esac
}

main() {
  local step
  for tool in az uv pwsh openssl; do command -v "$tool" >/dev/null || fail "Install $tool first."; done
  load_env
  DONE="" MISSING="" HUMAN=""
  say "Tenant $ENTRA_TENANT_ID, app $ENTRA_CLIENT_ID, mode $MODE$([ "$DRY_RUN" = 1 ] && echo ' (dry run)')"
  run_step login
  load_scopes
  for step in $STEPS; do run_step "$step"; done
  say "done: ${DONE# }"
  say "missing: ${MISSING# }"
  say "needs-human: ${HUMAN# }"
  [ "$DRY_RUN" = 1 ] || [ -z "$MISSING" ]
}
main
