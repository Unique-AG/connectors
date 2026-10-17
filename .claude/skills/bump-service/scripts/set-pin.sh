#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: set-pin.sh argocd <file> <service> tag <version>" >&2
  echo "       set-pin.sh argocd <file> <service> sha <full-sha> <version>" >&2
  echo "       set-pin.sh argocd <file> <service> dev <release-to-remember>" >&2
  echo "       set-pin.sh terraform <file> <service> <full-sha> <version>" >&2
  exit 2
}

[ $# -ge 4 ] || usage
mode=$1
file=$2
service=$3
marker="x-${service}-version"

require_sha() {
  [[ $1 =~ ^[0-9a-f]{40}$ ]] || { echo "error: $1 is not a full commit SHA" >&2; exit 1; }
}

rewrite() {
  local pattern=$1 tail=$2 expected stat
  expected=$(PATTERN=$pattern perl -ne '$n++ if /$ENV{PATTERN}/; END { print $n + 0 }' "$file")
  if [ "$expected" -eq 0 ]; then
    echo "error: no line in $file matches the $marker pin shape" >&2
    exit 1
  fi
  PATTERN=$pattern TAIL=$tail perl -pi -e 's/$ENV{PATTERN}/$1 . $ENV{TAIL}/e' "$file"
  stat=$(git diff --numstat -- "$file" | awk '{print $1 "/" $2}')
  if [ "$stat" != "$expected/$expected" ]; then
    echo "error: expected $expected changed line(s) in $file, git reports ${stat:-none}" >&2
    exit 1
  fi
  echo "ok: $file ($expected line(s))"
}

case "$mode" in
  argocd)
    pattern='^(\s*targetRevision: )\S+ # '"$marker"'.*$'
    case "$4" in
      tag)
        [ $# -eq 5 ] || usage
        rewrite "$pattern" "${service}@${5} # ${marker}"
        ;;
      sha)
        [ $# -eq 6 ] || usage
        require_sha "$5"
        rewrite "$pattern" "${5} # ${marker}: ${service}@${6}"
        ;;
      dev)
        [ $# -eq 5 ] || usage
        rewrite "$pattern" "dev/${service} # ${marker}: ${service}@${5}"
        ;;
      *)
        usage
        ;;
    esac
    ;;
  terraform)
    [ $# -eq 5 ] || usage
    require_sha "$4"
    rewrite '^(.*\?ref=)[0-9a-f]{40}"\s*# '"$marker"'.*$' "${4}\" # ${marker} ${service}@${5}"
    ;;
  *)
    usage
    ;;
esac
