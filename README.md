# skills

Personal agent skills with one canonical copy per skill under `skills/`.

## Install into a project

Skills are installed per project repo and committed there.

```sh
scripts/install-skills.sh path/to/project yt-md
scripts/install-skills.sh --check path/to/project yt-md
```

This copies each skill into `.agents/skills/<name>/` and links `.claude/skills -> ../.agents/skills` for Claude Code. Rerun it to update a copy.

From GitHub, without a local checkout:

```sh
npx skills add warrenwhipple/skills --skill yt-md
```

See [AGENTS.md](AGENTS.md) for the skill inventory and repository conventions.
