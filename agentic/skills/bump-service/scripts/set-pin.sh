#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: set-pin.sh argocd <file> <service> tag <version>" >&2
  echo "       set-pin.sh argocd <file> <service> sha <full-sha> <version>" >&2
  echo "       set-pin.sh argocd <file> <service> dev" >&2
  echo "       set-pin.sh terraform <file> <service> <full-sha> <version>" >&2
  exit 2
}

[ $# -ge 4 ] || usage
mode=$1
file=$2
service=$3
marker="x-${service}-version"

[[ $service =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "error: $service is not a service name" >&2; exit 1; }

require_sha() {
  [[ $1 =~ ^[0-9a-f]{40}$ ]] || { echo "error: $1 is not a full commit SHA" >&2; exit 1; }
}

require_version() {
  [[ $1 =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || { echo "error: $1 is not a version" >&2; exit 1; }
}

rewrite() {
  local pattern=$1 tail=$2 counts matched changed stat
  counts=$(PATTERN=$pattern TAIL=$tail perl -ne 'my $old = $_; if (s/$ENV{PATTERN}/$1 . $ENV{TAIL}/e) { $m++; $c++ if $_ ne $old } END { print $m + 0, " ", $c + 0 }' "$file")
  read -r matched changed <<< "$counts"
  if [ "$matched" -eq 0 ]; then
    echo "error: no line in $file matches the $marker pin shape" >&2
    exit 1
  fi
  if [ "$changed" -eq 0 ]; then
    echo "ok: $file ($matched pin(s) already at the target)"
    return
  fi
  PATTERN=$pattern TAIL=$tail perl -pi -e 's/$ENV{PATTERN}/$1 . $ENV{TAIL}/e' "$file"
  stat=$(git diff --numstat -- "$file" | awk '{print $1 "/" $2}')
  if [ "$stat" != "$changed/$changed" ]; then
    echo "error: expected $changed changed line(s) in $file, git reports ${stat:-none}" >&2
    exit 1
  fi
  echo "ok: $file ($changed line(s))"
}

case "$mode" in
  argocd)
    pattern='^(\s*targetRevision: )\S+ # '"$marker"'.*$'
    case "$4" in
      tag)
        [ $# -eq 5 ] || usage
        require_version "$5"
        rewrite "$pattern" "${service}@${5} # ${marker}"
        ;;
      sha)
        [ $# -eq 6 ] || usage
        require_sha "$5"
        require_version "$6"
        rewrite "$pattern" "${5} # ${marker}: ${service}@${6}"
        ;;
      dev)
        [ $# -eq 4 ] || usage
        rewrite "$pattern" "dev/${service}/main # ${marker}: rolling dev of main"
        ;;
      *)
        usage
        ;;
    esac
    ;;
  terraform)
    [ $# -eq 5 ] || usage
    require_sha "$4"
    require_version "$5"
    rewrite '^(.*\?ref=)[0-9a-f]{40}"\s*# '"$marker"'.*$' "${4}\" # ${marker} ${service}@${5}"
    ;;
  *)
    usage
    ;;
esac
