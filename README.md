# skills

Personal agent skills with one canonical copy per skill under `skills/`.

## Install from GitHub

```sh
npx skills add warrenwhipple/skills
gh skill install warrenwhipple/skills
```

## Local links

Run `scripts/link-skills.sh` to link each skill into both `~/.agents/skills/` and `~/.claude/skills/`. Existing real directories are moved to timestamped backups; unrelated installed skills remain in place.

The committed `.agents/skills` link points project-scoped tooling at the same canonical `skills/` directory.

See [AGENTS.md](AGENTS.md) for the skill inventory and repository conventions.
