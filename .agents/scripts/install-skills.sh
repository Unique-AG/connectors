#!/bin/bash
# Install skills from agentic/skills directories into .claude/skills.
# Safe to run repeatedly. See .agents/README.md for the one-time setup and the
# security implication of executing the Skills CLI from the npm registry.

set -euo pipefail

SKILLS_CLI_PACKAGE="skills@1.7.1"
STAMP_NAME=".agents-managed"
STAMP_LINE="managed-by: .agents/scripts/install-skills.sh"
MANIFEST_NAME=".agents-managed-manifest"

die() {
  printf 'install-skills: %s\n' "$1" >&2
  exit 1
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "$2"
  fi
}

contains_line() {
  local file="$1"
  local needle="$2"
  [[ -f "$file" ]] || return 1
  grep -Fxq -- "$needle" "$file"
}

stamp_matches() {
  local dest="$1"
  local line
  [[ -L "$dest" ]] && return 1
  [[ -f "$dest/$STAMP_NAME" ]] || return 1
  IFS= read -r line < "$dest/$STAMP_NAME" || return 1
  [[ "$line" == "$STAMP_LINE" ]]
}

write_manifest() {
  local source="$1"
  local tmp
  tmp=$(mktemp "$skills_dir/.manifest.XXXXXX") || die "cannot create a temporary manifest in $skills_dir"
  if ! {
    printf '%s\n' "# managed by .agents/scripts/install-skills.sh"
    if [[ -s "$source" ]]; then
      sort -u "$source"
    fi
  } > "$tmp"; then
    rm -f "$tmp"
    die "cannot write the managed-skill manifest"
  fi
  mv -f "$tmp" "$manifest"
}

remove_managed_skill() {
  local name="$1"
  local dest real_dest real_parent
  [[ "$name" =~ ^[a-z0-9._-]+$ ]] || die "refusing to remove unsafe skill name: $name"
  dest="$skills_dir/$name"
  [[ -e "$dest" || -L "$dest" ]] || return 0
  if [[ -L "$dest" ]]; then
    rm -- "$dest"
    printf 'install-skills: removed managed skill %s\n' "$name"
    return 0
  fi
  [[ -d "$dest" ]] || die "refusing to remove $dest because it is not a directory"
  real_dest=$(cd "$dest" && pwd -P) || die "cannot resolve $dest"
  real_parent=$(cd "$skills_dir" && pwd -P) || die "cannot resolve $skills_dir"
  [[ "$real_dest" == "$real_parent/$name" ]] || die "refusing to remove $dest because it resolves to $real_dest"
  rm -rf -- "$dest"
  printf 'install-skills: removed managed skill %s\n' "$name"
}

# plan | check. Arguments follow the subcommand.
run_node() {
  node - "$@" <<'EOF'
const fs = require('node:fs');
const path = require('node:path');

function fail(message) {
  console.error(`install-skills: ${message}`);
  process.exit(1);
}

function sanitize(name) {
  const cleaned = name
    .toLowerCase()
    .replace(/[^a-z0-9._]+/g, '-')
    .replace(/^[.\-]+|[.\-]+$/g, '')
    .slice(0, 255);
  return cleaned || 'unnamed-skill';
}

function readFrontmatterName(skillMdPath) {
  const text = fs.readFileSync(skillMdPath, 'utf8');
  if (!text.startsWith('---\n') && !text.startsWith('---\r\n')) {
    fail(`${skillMdPath} is missing YAML frontmatter`);
  }
  const match = text.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!match) {
    fail(`${skillMdPath} has unterminated YAML frontmatter`);
  }
  const nameLine = match[1].match(/^name:[ \t]*(.*)$/m);
  if (!nameLine) {
    fail(`${skillMdPath} frontmatter is missing name`);
  }
  let value = nameLine[1].trim();
  if (
    (value.startsWith('"') && value.endsWith('"') && value.length >= 2) ||
    (value.startsWith("'") && value.endsWith("'") && value.length >= 2)
  ) {
    value = value.slice(1, -1);
  }
  if (!value || /[\t\r\n]/.test(value)) {
    fail(`${skillMdPath} has an empty or multi-line frontmatter name`);
  }
  return value;
}

function discover(dir) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (error) {
    fail(`cannot read ${dir}: ${error.message}`);
  }
  if (entries.some((entry) => entry.isFile() && entry.name === 'SKILL.md')) {
    return [dir];
  }
  const found = [];
  for (const entry of entries) {
    if (entry.name === 'node_modules' || entry.name === '.git') {
      continue;
    }
    if (!entry.isDirectory()) {
      continue;
    }
    found.push(...discover(path.join(dir, entry.name)));
  }
  return found;
}

function plan(containers) {
  const byDest = new Map();
  for (const container of containers) {
    if (!fs.existsSync(container) || !fs.statSync(container).isDirectory()) {
      fail(`skill directory does not exist: ${container}`);
    }
    for (const skillDir of discover(container)) {
      const frontmatterName = readFrontmatterName(path.join(skillDir, 'SKILL.md'));
      const sanitized = sanitize(frontmatterName);
      if (!/^[a-z0-9._-]+$/.test(sanitized)) {
        fail(`refusing unsafe install directory for ${skillDir}: ${sanitized}`);
      }
      if (/[\t\r\n]/.test(container)) {
        fail(`refusing a skill directory whose path contains a tab or newline: ${container}`);
      }
      const previous = byDest.get(sanitized);
      if (previous) {
        fail(
          `${skillDir} and ${previous.skillDir} both install to .claude/skills/${sanitized}. Give them distinct frontmatter names.`,
        );
      }
      byDest.set(sanitized, { frontmatterName, container, skillDir });
    }
  }
  for (const sanitized of [...byDest.keys()].sort()) {
    const row = byDest.get(sanitized);
    process.stdout.write(`${sanitized}\t${row.frontmatterName}\t${row.container}\n`);
  }
}

function check(skillsDir, expectedFile, jsonFiles) {
  const expected = new Set(
    fs
      .readFileSync(expectedFile, 'utf8')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean),
  );
  const data = [];
  for (const jsonFile of jsonFiles) {
    let parsed;
    try {
      parsed = JSON.parse(fs.readFileSync(jsonFile, 'utf8'));
    } catch (error) {
      fail(
        `Skills CLI did not return JSON (${error.message}). The first run downloads ${process.env.SKILLS_CLI_PACKAGE} from the npm registry.`,
      );
    }
    if (!Array.isArray(parsed)) {
      fail('Skills CLI JSON was not an array');
    }
    data.push(...parsed);
  }
  const skillsReal = fs.realpathSync(skillsDir);
  const installed = new Set();
  for (const item of data) {
    if (!item || item.status !== 'installed' || typeof item.path !== 'string') {
      const name = item && item.name ? item.name : '<unknown>';
      const reason = (item && (item.error || item.status)) || 'failed';
      fail(`failed to install ${name}: ${reason}`);
    }
    const resolved = path.resolve(item.path);
    let installedReal;
    try {
      installedReal = fs.realpathSync(resolved);
    } catch (error) {
      fail(`installed skill is missing at ${item.path}: ${error.message}`);
    }
    if (path.dirname(installedReal) !== skillsReal) {
      fail(`refusing unexpected install path ${item.path}`);
    }
    const base = path.basename(installedReal);
    if (!/^[a-z0-9._-]+$/.test(base)) {
      fail(`refusing unexpected install directory name ${base}`);
    }
    installed.add(base);
  }
  for (const name of expected) {
    if (!installed.has(name)) {
      fail(`Skills CLI did not install ${name} into .claude/skills`);
    }
  }
  for (const name of installed) {
    if (!expected.has(name)) {
      fail(`Skills CLI installed unexpected skill ${name}`);
    }
  }
  const names = [...installed].sort();
  if (names.length > 0) {
    process.stdout.write(`${names.join('\n')}\n`);
  }
}

const command = process.argv[2];
try {
  if (command === 'plan') {
    plan(process.argv.slice(3));
  } else if (command === 'check') {
    check(process.argv[3], process.argv[4], process.argv.slice(5));
  } else {
    fail(`unknown helper command: ${command}`);
  }
} catch (error) {
  fail(error && error.message ? error.message : String(error));
}
EOF
}

root=$(git rev-parse --show-toplevel 2>/dev/null) || die "run this inside the repository"
cd "$root"

skills_dir="$root/.claude/skills"
manifest="$skills_dir/$MANIFEST_NAME"

tmpdir=$(mktemp -d) || die "cannot create a temporary directory"
trap 'rm -rf "$tmpdir"' EXIT

mkdir -p "$skills_dir"

: > "$tmpdir/managed"
if [[ -f "$manifest" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line=${line%$'\r'}
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" =~ ^[a-z0-9._-]+$ ]] || die "invalid managed-skill name in $manifest: $line"
    printf '%s\n' "$line" >> "$tmpdir/managed"
  done < "$manifest"
fi

if [[ -d "$skills_dir" ]]; then
  while IFS= read -r -d '' stamp; do
    skill_dir=$(dirname "$stamp")
    [[ -L "$skill_dir" ]] && continue
    name=$(basename "$skill_dir")
    [[ "$name" =~ ^[a-z0-9._-]+$ ]] || continue
    if stamp_matches "$skill_dir"; then
      printf '%s\n' "$name" >> "$tmpdir/managed"
    fi
  done < <(find "$skills_dir" -mindepth 2 -maxdepth 2 -name "$STAMP_NAME" -type f -print0)
fi
if [[ -s "$tmpdir/managed" ]]; then
  sort -u "$tmpdir/managed" -o "$tmpdir/managed"
fi

containers=()
if [[ -d "$root/agentic/skills" ]]; then
  containers+=("$root/agentic/skills")
fi
for dir in "$root"/services/*/agentic/skills; do
  [[ -d "$dir" ]] || continue
  containers+=("$dir")
done

: > "$tmpdir/planned"
if [[ ${#containers[@]} -eq 0 ]]; then
  printf 'install-skills: no agentic/skills directories; removing script-managed skills only\n'
else
  require_cmd node "Node.js is required to read skill frontmatter. Install Node.js, then re-run bash .agents/scripts/setup.sh"
  run_node plan "${containers[@]}" > "$tmpdir/planned"
fi

: > "$tmpdir/install.tsv"
: > "$tmpdir/install.names"
: > "$tmpdir/install.sanitized"
while IFS=$'\t' read -r sanitized frontmatter source || [[ -n "${sanitized:-}" ]]; do
  [[ -z "${sanitized:-}" ]] && continue
  [[ -n "${frontmatter:-}" ]] || die "could not read the frontmatter name for $sanitized"
  [[ -n "${source:-}" ]] || die "could not read the source directory for $sanitized"
  dest="$skills_dir/$sanitized"
  if [[ -e "$dest" || -L "$dest" ]] && ! contains_line "$tmpdir/managed" "$sanitized"; then
    printf 'install-skills: leaving %s in place; it was not installed by this script\n' "$dest" >&2
    continue
  fi
  printf '%s\t%s\t%s\n' "$sanitized" "$frontmatter" "$source" >> "$tmpdir/install.tsv"
  printf '%s\n' "$frontmatter" >> "$tmpdir/install.names"
  printf '%s\n' "$sanitized" >> "$tmpdir/install.sanitized"
done < "$tmpdir/planned"

: > "$tmpdir/installed"
if [[ -s "$tmpdir/install.names" ]]; then
  require_cmd npx "npx is required to run the Skills CLI (${SKILLS_CLI_PACKAGE} from the npm registry). Install Node.js, then re-run bash .agents/scripts/setup.sh"
  sort -u "$tmpdir/managed" "$tmpdir/install.sanitized" > "$tmpdir/manifest.pre"
  write_manifest "$tmpdir/manifest.pre"

  skill_count=$(wc -l < "$tmpdir/install.names" | tr -d ' ')
  printf 'install-skills: installing %s skill(s) with %s\n' "$skill_count" "$SKILLS_CLI_PACKAGE"

  json_index=0
  : > "$tmpdir/json.list"
  while IFS= read -r source || [[ -n "$source" ]]; do
    [[ -z "$source" ]] && continue
    [[ -d "$source" ]] || die "skill source does not exist: $source"
    names_file="$tmpdir/names.$json_index"
    : > "$names_file"
    while IFS=$'\t' read -r sanitized frontmatter src || [[ -n "${sanitized:-}" ]]; do
      [[ -z "${sanitized:-}" ]] && continue
      [[ "$src" == "$source" ]] || continue
      printf '%s\n' "$frontmatter" >> "$names_file"
    done < "$tmpdir/install.tsv"

    cmd=(npx --yes "$SKILLS_CLI_PACKAGE" add "$source" -a claude-code -y --json)
    while IFS= read -r skill_name || [[ -n "$skill_name" ]]; do
      [[ -z "$skill_name" ]] && continue
      cmd+=(--skill "$skill_name")
    done < "$names_file"

    json_file="$tmpdir/cli-$json_index.json"
    err_file="$tmpdir/cli-$json_index.err"
    set +e
    INSTALL_INTERNAL_SKILLS=1 DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 SKILLS_CLI_PACKAGE="$SKILLS_CLI_PACKAGE" \
      "${cmd[@]}" >"$json_file" 2>"$err_file"
    status=$?
    set -e
    if [[ "$status" -ne 0 ]]; then
      printf 'install-skills: Skills CLI failed (exit %s) for %s.\n' "$status" "$source" >&2
      printf 'install-skills: the script downloads and executes %s from the npm registry. See .agents/README.md.\n' "$SKILLS_CLI_PACKAGE" >&2
      cat "$err_file" >&2 || true
      if [[ -s "$json_file" ]]; then
        printf 'install-skills: CLI output:\n' >&2
        cat "$json_file" >&2
      fi
      exit "$status"
    fi
    printf '%s\n' "$json_file" >> "$tmpdir/json.list"
    json_index=$((json_index + 1))
  done < <(cut -f3 "$tmpdir/install.tsv" | sort -u)

  json_args=()
  while IFS= read -r json_file || [[ -n "$json_file" ]]; do
    [[ -z "$json_file" ]] && continue
    json_args+=("$json_file")
  done < "$tmpdir/json.list"
  if [[ ${#json_args[@]} -eq 0 ]]; then
    die "Skills CLI produced no install result"
  fi
  run_node check "$skills_dir" "$tmpdir/install.sanitized" "${json_args[@]}" > "$tmpdir/installed"

  while IFS= read -r name || [[ -n "$name" ]]; do
    [[ -z "$name" ]] && continue
    dest="$skills_dir/$name"
    if [[ -L "$dest" || ! -d "$dest" ]]; then
      die "Skills CLI did not create a real directory at $dest"
    fi
    printf '%s\n' "$STAMP_LINE" > "$dest/$STAMP_NAME"
    printf 'install-skills: installed %s\n' "$name"
  done < "$tmpdir/installed"
fi

if [[ -s "$tmpdir/managed" ]]; then
  while IFS= read -r name || [[ -n "$name" ]]; do
    [[ -z "$name" ]] && continue
    if contains_line "$tmpdir/installed" "$name"; then
      continue
    fi
    remove_managed_skill "$name"
  done < "$tmpdir/managed"
fi

write_manifest "$tmpdir/installed"
