# ADR 0001: Repository layout and distribution

Date: 2026-07-14

## Status

Accepted

## Decision

Canonical skills live in a flat `skills/<name>/` layout at the repository root. Flat placement keeps every skill discoverable by Zed, the lowest common denominator among the target harnesses. The repository commits `.agents/skills -> ../skills` for neutral and project-scoped discovery, and `CLAUDE.md -> AGENTS.md` so harness guidance has one source.

Skills use only the core Agent Skills structure: `SKILL.md` with `name` and `description` frontmatter, plus optional `scripts/`, `references/`, and `assets/`. Descriptions stay terse and within roughly 1024 bytes. A `SKILL.md` body stays below 500 lines, with longer material moved to `references/`.

Local installation uses per-skill symlinks from both `~/.agents/skills/<name>` and `~/.claude/skills/<name>` to the canonical repository folders. Per-skill links let third-party skills coexist. Existing real directories are backed up before links replace their locations; copies are not synchronized.

The repository itself is the distribution unit. Consumers install it with `npx skills add warrenwhipple/skills` or `gh skill install warrenwhipple/skills`. Cloud/plugin packaging for Cowork and ChatGPT Work is deferred.

## Alternatives rejected

Category subfolders were rejected because Zed does not discover nested skills. Copy-based synchronization was rejected because copies drift and create competing canonical versions. Plugin-first packaging was rejected because local harness discovery and repository-based distribution need no wrapper, while cloud packaging can be added later if required.
