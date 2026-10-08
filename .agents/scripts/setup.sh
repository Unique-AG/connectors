#!/bin/bash
# Point this clone at the shared hooks and install canonical skills.
# Git does not enable version-controlled hooks on clone or pull; run this once per clone.
# See .agents/README.md.

set -euo pipefail

TARGET=".agents/hooks"

die() {
  printf 'setup: %s\n' "$1" >&2
  exit 1
}

contains_line() {
  local file="$1"
  local needle="$2"
  [[ -f "$file" ]] || return 1
  grep -Fxq -- "$needle" "$file"
}

confirm_or_exit() {
  local prompt="$1"
  local reply
  printf '\n%s\n' "$prompt" >&2
  if [[ ! -t 0 ]]; then
    cat >&2 <<'EOF'
Refusing to change core.hooksPath without a terminal.
Re-run bash .agents/scripts/setup.sh in a terminal and confirm, or set it yourself:

  git config --local core.hooksPath .agents/hooks

Existing hook files were not modified.
EOF
    exit 1
  fi
  printf 'Set core.hooksPath to %s? [y/N] ' "$TARGET" >&2
  read -r reply || die "could not read confirmation"
  case "$reply" in
    y | Y | yes | YES) ;;
    *)
      printf 'Left core.hooksPath unchanged. Existing hook files were not modified.\n' >&2
      printf 'Run bash .agents/scripts/install-skills.sh to install skills without changing hooks.\n' >&2
      exit 1
      ;;
  esac
}

append_custom_hooks() {
  local dir="$1"
  local out="$2"
  local seen="$3"
  local real base
  [[ -d "$dir" ]] || return 0
  real=$(cd "$dir" && pwd -P) || return 0
  if contains_line "$seen" "$real"; then
    return 0
  fi
  printf '%s\n' "$real" >> "$seen"
  for hook in "$dir"/* "$dir"/.*; do
    [[ -e "$hook" ]] || continue
    base=$(basename "$hook")
    case "$base" in
      . | .. | *.sample) continue ;;
    esac
    printf '%s\n' "$base" >> "$out"
  done
}

root=$(git rev-parse --show-toplevel 2>/dev/null) || die "run this inside the repository"
cd "$root"
[[ -d "$root/$TARGET" ]] || die "missing $TARGET"

current=$(git config --local --get core.hooksPath || true)
current=${current%/}

already=0
if [[ -n "$current" ]]; then
  if [[ "$current" == "$TARGET" ]]; then
    already=1
  else
    current_real=""
    target_real=""
    if [[ "$current" == /* ]]; then
      current_dir=$(cd "$(dirname "$current")" 2>/dev/null && pwd -P) || true
      if [[ -n "${current_dir:-}" ]]; then
        current_real="$current_dir/$(basename "$current")"
      fi
    elif [[ -d "$root/$current" ]]; then
      current_real=$(cd "$root/$current" && pwd -P) || true
    fi
    if [[ -d "$root/$TARGET" ]]; then
      target_real=$(cd "$root/$TARGET" && pwd -P) || true
    fi
    if [[ -n "$current_real" && "$current_real" == "$target_real" ]]; then
      already=1
    fi
  fi
fi

if [[ "$already" -eq 0 && -n "$current" ]]; then
  cat >&2 <<EOF
core.hooksPath is currently '$current'.
Switching it to $TARGET stops Git from running hooks in '$current'.
Those hook files are left in place.
EOF
  confirm_or_exit "A custom hooks path is already configured."
fi

if [[ "$already" -eq 0 && -z "$current" ]]; then
  tmp=$(mktemp -d) || die "cannot create a temporary directory"
  trap 'rm -rf "$tmp"' EXIT
  : > "$tmp/hooks"
  : > "$tmp/seen"
  append_custom_hooks "$(git rev-parse --git-path hooks)" "$tmp/hooks" "$tmp/seen"
  common_dir=$(git rev-parse --git-common-dir)
  case "$common_dir" in
    /*) ;;
    *) common_dir="$root/$common_dir" ;;
  esac
  append_custom_hooks "$common_dir/hooks" "$tmp/hooks" "$tmp/seen"
  if [[ -s "$tmp/hooks" ]]; then
    printf 'This clone has local Git hooks outside %s:\n' "$TARGET" >&2
    sort -u "$tmp/hooks" | while IFS= read -r hook; do
      printf '  %s\n' "$hook" >&2
    done
    cat >&2 <<EOF
Setting core.hooksPath to $TARGET leaves those files in place, but Git will stop running them.
EOF
    confirm_or_exit "Local Git hooks are already installed."
  fi
  trap - EXIT
  rm -rf "$tmp"
fi

if [[ "$already" -eq 0 ]]; then
  git config --local core.hooksPath "$TARGET"
  printf 'Set core.hooksPath to %s\n' "$TARGET"
else
  printf 'core.hooksPath is already %s\n' "$TARGET"
fi

bash "$root/.agents/scripts/install-skills.sh"
