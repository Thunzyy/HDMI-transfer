# GitHub Agile workflow for Codex

This repository uses the Lucas GitHub Agile workflow so Codex can work directly without needing Hermes chat.

## Source of truth

- GitHub Issues contain the feature/bug/task spec, acceptance criteria, decisions, handoff comments, and verification evidence.
- GitHub Project tracks status with this flow: `Feature Idea` -> `Backlog` -> `Ready` -> `In progress` -> `In review` -> `Done`.
- Repository metadata lives in `.github/hermes-agile.json`.
- Chat history is not the source of truth. If it matters, write it to the issue/PR/project.

## Local helper commands

On PCFIXE, these wrappers are on PATH:

```powershell
agile-setup        # initialize/reuse the GitHub Project workflow for this repo
agile-inventory    # list local repos and whether they have Agile metadata
agile-feature      # create an unapproved Feature Idea issue/project item
agile-start        # start an approved issue: branch + Project -> In progress
agile-handoff      # push/comment/evidence + Project -> In review/Done
agile-field        # set a GitHub Project field for an issue
codex-agile        # launch Codex with this workflow preloaded
```

Legacy aliases also exist: `hermes-agile-setup`, `hermes-feature-idea`, `hermes-work-start`, `hermes-work-handoff`, `hermes-project-field`.

## Mandatory Codex behavior

When working directly as Codex:

1. Read this `AGENTS.md`, `.github/hermes-agile.json`, and the linked GitHub issue before editing code.
2. Do not implement an issue whose `Decision` is `Proposed`, `Needs Discussion`, `Rejected`, or `Parked`, unless Lucas explicitly approves in the issue or prompt.
3. Start approved implementation from an issue with:

   ```powershell
   agile-start -Issue <number>
   ```

4. Keep changes on the issue branch. Prefer small commits with conventional commit messages.
5. Run relevant tests/lint/build/smoke checks. Capture exact commands and results.
6. Before ending, always leave a durable handoff:

   ```powershell
   agile-handoff -Issue <number> -Summary "<what changed / what remains>" -Evidence "<tests and checks>" -Status "In review" -Push
   ```

7. Mark `Done` only when verification evidence is sufficient. Otherwise use `In review`.
8. If blocked, comment on the issue with the blocker, current branch, current HEAD, and next needed decision.

## Quick direct-Codex examples

```powershell
# Start issue 42 and let Codex implement with workspace-write permissions
codex-agile -Issue 42 -Prompt "Implement the acceptance criteria" -Auto

# Interactive Codex session with the Agile context preloaded
codex-agile -Issue 42 -Interactive

# Create an idea without implementing it
agile-feature -Title "Offline mode" -Body "Motivation and rough behavior" -Priority P3
```
