#!/usr/bin/env bash
set -euo pipefail

usage() { echo "usage: tools.sh <service> <from-version> <to-version>" >&2; exit 2; }
[ $# -eq 3 ] || usage
service=$1 from=$2 to=$3
[[ $service =~ ^[a-z0-9][a-z0-9-]*$ ]] || usage
[[ $from =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && $to =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || usage

cd "$(git rev-parse --show-toplevel)"
git fetch -q --tags origin
a="$service@$from"
b="$service@$to"
for tag in "$a" "$b"; do
  git rev-parse -q --verify "refs/tags/$tag" > /dev/null || { echo "error: the tag $tag does not exist" >&2; exit 1; }
done

declared() {
  git grep -lE '^[[:space:]]*@(Tool|(mcp\.)?tool)\(' "$1" -- "services/$service/src" | sed "s/^$1://" | while read -r file; do
    git show "$1:$file" | FILE=$file perl -0777 -ne '
      my %c = /^(\w+)(?:\s*:\s*[^=\n]+)?\s*=\s*"([^"]+)"/mg;
      while (/^[ \t]*@(?:Tool|(?:mcp\.)?tool)\(/mg) {
        my ($rest) = split /^[ \t]*@(?:Tool|(?:mcp\.)?tool)\(/m, substr($_, pos), 2;
        my $n = "?";
        if (substr($rest, 0, 500) =~ /\bname\s*[:=]\s*(?:\x27([^\x27]+)\x27|"([^"]+)"|(\w+))/) { $n = $1 // $2 // $c{$3} // $3 }
        elsif ($rest =~ /\bdef\s+(\w+)/) { $n = $1 }
        print "$n\t$ENV{FILE}\n";
      }'
  done | sort -u || true
}

before=$(declared "$a")
after=$(declared "$b")
names() { cut -f1 <<< "$1" | grep . || true; }

printf '# %s %s -> %s\n' "$service" "$from" "$to"
if [ -z "$before$after" ]; then echo "(no tool declarations)"; exit 0; fi
printf '== tools added\n'
comm -13 <(names "$before" | sort) <(names "$after" | sort) | grep . || echo "(none)"
printf '== tools removed\n'
comm -23 <(names "$before" | sort) <(names "$after" | sort) | grep . || echo "(none)"
printf '== tools in both, whose file changed (read the diff for a changed description, parameter, or annotation)\n'
found=0
while IFS=$'\t' read -r name file; do
  grep -qxF "$name" <(names "$before") || continue
  git cat-file -e "$a:$file" 2> /dev/null || { echo "$name: moved to $file"; found=1; continue; }
  lines=$(git diff -U0 "$a" "$b" -- "$file" | grep -E "^[+-][^+-].*[\"']" | grep -Ev "^[+-][[:space:]]*(import|from|#|//)" || true)
  [ -n "$lines" ] || continue
  found=1
  printf '%s (%s): %s changed lines with text\n' "$name" "$file" "$(wc -l <<< "$lines" | tr -d ' ')"
  head -6 <<< "$lines" | cut -c1-170 | sed 's/^/    /'
done <<< "$after"
if [ "$found" = 0 ]; then echo "(none)"; fi
