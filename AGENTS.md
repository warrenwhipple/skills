# Agent Skills

This repository is the canonical home for Warren Whipple's personal agent skills.

## Inventory

- `mirror-check` — Check or create human-owned MIRROR files for drift and misunderstandings.
- `yt-md` — Capture YouTube transcripts as Markdown with temporary safe-ingestion data.

## Conventions

- Keep skills directly under `skills/<name>/`; do not add category subfolders.
- Use the core Agent Skills structure: `SKILL.md` plus optional `scripts/`, `references/`, and `assets/`; allow only the harness metadata documented below as an exception.
- Keep `name` equal to the kebab-case folder name.
- Make `description` say what the skill does and when it should trigger, within about 1024 bytes.
- Keep each `SKILL.md` body below 500 lines; move overflow into `references/`.
- See [`docs/manual-only-skills.md`](docs/manual-only-skills.md) when a skill must load only after explicit human invocation; it documents the supported harness metadata.

## Harnesses

- Neutral project tooling uses the committed `.agents/skills -> ../skills` link.
- Zed, Codex CLI, OpenCode, and Cursor use per-skill links under `~/.agents/skills/`.
- Claude Code uses per-skill links under `~/.claude/skills/`.
- Run `scripts/link-skills.sh` to create or refresh local links without replacing third-party skills.
- Cowork and ChatGPT Work require cloud/plugin packaging. That packaging is deferred.
