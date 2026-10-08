# Agent skills

Server-specific skills live in `services/<svc>/agentic/skills/`. Skills that are not specific to one server live in `agentic/skills/` at the repository root. The Skills CLI installs them into `.claude/skills/`. That directory is gitignored, and it is the only agent skills directory we keep.

Claude does not understand the `.agentic/skills` standard yet. Once it does, move these skills to `.agentic/skills` and stop installing them into `.claude/skills/`.

Git does not turn on hooks when you clone or pull. Run this once in each clone:

```bash
bash agentic/skill-management/setup.sh
```

The command is safe to repeat. It sets `core.hooksPath` to `agentic/hooks` and installs the current skills. If this clone already has a different `core.hooksPath`, or executable hooks under `.git/hooks`, setup prints a warning and asks before changing the path. It does not delete those hook files. Decline, and the existing path stays as it is.

To refresh the installed skills by hand, after editing one or without pulling:

```bash
bash agentic/skill-management/update-skills.sh
```

After setup:

- A `git pull` that merges or fast-forwards runs `agentic/hooks/post-merge`.
- A `git pull --rebase` that replays local commits runs `agentic/hooks/post-rewrite`. A fast-forward rebase does not rewrite commits; Git runs `post-merge` for that update instead. `git commit --amend` does not install skills.

Both hooks call `agentic/skill-management/install-skills.sh`. Running it again replaces the managed copies in place, so repeated pulls do not create duplicate skills. When a skill disappears from `agentic/skills/`, the script deletes that installed copy only if this script created it (a stamp file inside the skill, recorded in `.claude/skills/.skill-managed-manifest`). Other files under `.claude/`, including skills you installed yourself, are left alone.

## Security

Installation runs `npx --yes skills@1.7.1`. That downloads the [Skills CLI](https://skills.sh/) from the npm registry and executes it. The first run needs network access; later runs can use the npm cache. Run the script only if you trust that package and the contents of the `agentic/skills/` trees.

The script sets `DISABLE_TELEMETRY=1` and `DO_NOT_TRACK=1`. It also sets `INSTALL_INTERNAL_SKILLS=1`, so skills marked `metadata.internal: true` are installed with the rest. The CLI writes `skills-lock.json` at the repository root. That file is gitignored.

The CLI is invoked as `npx skills add <agentic/skills> -a claude-code -y`, once per `agentic/skills/` directory. With Claude Code as the only target, skills.sh 1.7.1 installs the files into `.claude/skills/` and does not create a second skills tree.
