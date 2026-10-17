# ADR 0002: Per-repo installation

Date: 2026-10-17

## Status

Accepted. Supersedes the local installation paragraph of [ADR 0001](0001-repo-layout.md).

## Decision

Skills are installed into the project repos that use them, not into user-level harness directories. Each project commits copies under `.agents/skills/<name>/` and a `.claude/skills -> ../.agents/skills` link so Claude Code and `.agents`-aware harnesses share one folder. `scripts/install-skills.sh` performs the copy and reports drift with `--check`.

This repository stays agnostic to the machine it is on: no absolute paths, home-directory layouts, or assumptions about where other repos are checked out.

## Consequences

Projects work on any machine, in fresh clones, and in cloud sessions without a local install step. Copies can drift from this repository, so updates are explicit reinstalls and `--check` finds stale copies.

## Alternatives rejected

User-level symlinks were dropped because every skill so far serves one or two specific repos, and global installation put unrelated skills in every session's context. Per-repo symlinks to a local checkout were rejected because they depend on where this repository is checked out and break in fresh clones and cloud sessions.
