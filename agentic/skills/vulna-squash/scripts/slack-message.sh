#!/usr/bin/env bash
set -euo pipefail

awk -v max_lines=5 -v max_chars=200 -v repo=Unique-AG/connectors '
function die(msg) { print msg > "/dev/stderr"; failed = 1; exit 1 }
function link(s,   out, num) {
  while (match(s, /#[0-9]+/)) {
    num = substr(s, RSTART + 1, RLENGTH - 1)
    out = out substr(s, 1, RSTART - 1) "<https://github.com/" repo "/pull/" num "|#" num ">"
    s = substr(s, RSTART + RLENGTH)
  }
  return out s
}
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
}
kind == "pr" {
  if (split(text, part, " ") != 2 || part[1] !~ /^[0-9]+$/) die("A pr line needs a PR number and a status.")
  prs[++pr_count] = link("#" part[1]) " " part[2]
  next
}
kind in prefix {
  text = prefix[kind] text
  if (length(text) > max_chars) die("A " kind " line is longer than " max_chars " characters.")
  extra[++extra_count] = link(text)
  next
}
{ die("Unknown line kind: " kind ". Use pr, stop, app, os, lockfiles or note.") }
END {
  if (failed) exit 1
  if (pr_count + extra_count == 0) die("The message is empty.")
  if (extra_count + (pr_count > 0) > max_lines) die("The message has more than " max_lines " lines.")
  for (i = 1; i <= extra_count; i++) print extra[i]
  if (pr_count > 0) {
    line = "PRs: " prs[1]
    for (i = 2; i <= pr_count; i++) line = line " · " prs[i]
    print line
  }
}'
