#!/usr/bin/env bash
# Copy skills from this repo into a project repo.
#
# Usage: install-skills.sh [--check] <project-dir> <skill>...
#
# Copies skills/<skill>/ to <project-dir>/.agents/skills/<skill>/, replacing
# any previous copy, and points <project-dir>/.claude/skills at .agents/skills.
# With --check, reports installed copies that differ from this repo instead.

set -euo pipefail

usage() {
  printf 'Usage: %s [--check] <project-dir> <skill>...\n' "$(basename "$0")" >&2
  exit 2
}

check=false
if [[ "${1:-}" == "--check" ]]; then
  check=true
  shift
fi
[[ $# -ge 2 ]] || usage

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project="$(cd "$1" && pwd)"
shift

dest_dir="$project/.agents/skills"
status=0

for name in "$@"; do
  src="$repo_root/skills/$name"
  dest="$dest_dir/$name"

  if [[ ! -f "$src/SKILL.md" ]]; then
    printf 'Unknown skill: %s\n' "$name" >&2
    status=1
    continue
  fi

  if $check; then
    if [[ ! -d "$dest" ]]; then
      printf 'missing  %s\n' "$name"
      status=1
    elif ! diff -rq -x __pycache__ "$src" "$dest" >/dev/null; then
      printf 'drifted  %s\n' "$name"
      status=1
    else
      printf 'current  %s\n' "$name"
    fi
    continue
  fi

  mkdir -p "$dest_dir"
  rm -rf "$dest"
  rsync -a --exclude __pycache__ "$src/" "$dest/"
  printf 'Installed %s -> %s\n' "$name" "$dest"
done

if ! $check; then
  claude_skills="$project/.claude/skills"
  if [[ ! -e "$claude_skills" && ! -L "$claude_skills" ]]; then
    mkdir -p "$project/.claude"
    ln -s ../.agents/skills "$claude_skills"
    printf 'Linked %s -> ../.agents/skills\n' "$claude_skills"
  elif [[ "$(readlink "$claude_skills" || true)" != "../.agents/skills" ]]; then
    printf 'Note: %s is not a link to ../.agents/skills; Claude Code may not see these skills.\n' "$claude_skills" >&2
  fi
fi

exit "$status"
