# Agent Skills

This repository is the canonical home for Warren Whipple's personal agent skills.

## Inventory

- `brew-upgrade` — Review outdated Homebrew packages as a decision sheet, then run and verify only the approved upgrades.
- `mirror-check` — Check or create human-owned MIRROR files for drift and misunderstandings.
- `yt-md` — Capture YouTube transcripts as Markdown with temporary safe-ingestion data.

## Conventions

- Keep skills directly under `skills/<name>/`; do not add category subfolders.
- Use the core Agent Skills structure: `SKILL.md` plus optional `scripts/`, `references/`, and `assets/`; allow only the harness metadata documented below as an exception.
- Keep `name` equal to the kebab-case folder name.
- Make `description` say what the skill does and when it should trigger, within about 1024 bytes.
- Keep each `SKILL.md` body below 500 lines; move overflow into `references/`.
- See [`docs/manual-only-skills.md`](docs/manual-only-skills.md) when a skill must load only after explicit human invocation; it documents the supported harness metadata.

## Installation

- Install skills per project repo, not at the user level. See [ADR 0002](docs/adr/0002-per-repo-install.md).
- Run `scripts/install-skills.sh <project-dir> <skill>...` to copy skills into `<project-dir>/.agents/skills/` and link `.claude/skills -> ../.agents/skills`.
- Run `scripts/install-skills.sh --check <project-dir> <skill>...` to find installed copies that have drifted from this repo.
- Keep docs and skills free of machine-specific paths and local folder layouts.
- This repo's committed `.agents/skills -> ../skills` link exposes its own skills while working here.
- Cowork and ChatGPT Work require cloud/plugin packaging. That packaging is deferred.
