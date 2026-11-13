#!/usr/bin/env bash
set -euo pipefail

awk -v max_lines=5 -v max_chars=200 '
function die(msg) { print msg > "/dev/stderr"; failed = 1; exit 1 }
BEGIN {
  prefix["stop"] = "Stopped: "
  prefix["app"] = "App: "
  prefix["os"] = "OS: "
  prefix["lockfiles"] = "Lockfiles: "
  prefix["note"] = ""
}
NF == 0 { next }
{
  kind = $1
  text = $0
  sub(/^[ \t]*[^ \t]+[ \t]*/, "", text)
  if (text == "") die("A " kind " line has no text.")
  if (kind in prefix) text = prefix[kind] text
  if (length(text) > max_chars) die("A " kind " line is longer than " max_chars " characters.")
}
kind == "pr" { prs[++pr_count] = text; next }
kind in prefix { extra[++extra_count] = text; next }
{ die("Unknown line kind: " kind ". Use pr, stop, app, os, lockfiles or note.") }
END {
  if (failed) exit 1
  if (pr_count + extra_count == 0) die("The message is empty.")
  room = max_lines - extra_count
  if (pr_count > 0 && room < 1) die("The note and stop lines leave no room for the PR lines.")
  if (extra_count > max_lines) die("There are more than " max_lines " note and stop lines.")
  keep = (pr_count <= room) ? pr_count : room - 1
  for (i = 1; i <= keep; i++) print prs[i]
  if (keep < pr_count) {
    rest = prs[keep + 1]
    for (i = keep + 2; i <= pr_count; i++) rest = rest " ; " prs[i]
    print rest
  }
  for (i = 1; i <= extra_count; i++) print extra[i]
}'
