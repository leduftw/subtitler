# subtitler

Subtitles for any video, in any language: a zero-dependency Python command that
turns video or audio into speaker-aware SRT files through hosted speech models.

## Rules for this repo

- Run `python3 -m unittest discover tests` before committing; never commit a red suite.
- Never commit secrets or media. API key files, `samples/`, `outputs/` and `.work/`
  are gitignored on purpose; keep it that way.
- Don't commit generated `outputs/*.srt`; they're local artifacts.

## Testing

Standard library only, no test dependencies:

```sh
python3 -m unittest discover tests
```

The project has **zero runtime dependencies** and should stay that way — it uses
`urllib`, `dataclasses`, `difflib`, and `argparse` rather than `requests`, `httpx`,
or an SDK. Adding a dependency needs a real justification.

## Architecture invariants

- Providers return `list[Cue]`, never formatted SRT text. Rendering, line wrapping,
  and speaker labelling happen once in `srt.py`.
- A cue must never span two speakers. That guarantee lives in
  `group_words_into_cues`, not in individual providers.
- A provider whose `SPEC` sets `internal=True` stays registered and reusable but is
  hidden from `--provider` choices (this is how `azure-mai` survives as
  `azure-hybrid`'s text pass without being user-selectable).

See `docs/system.md` for the full design.

<!-- playbook:begin -->
## How work lands here

> Managed by [leduftw/playbook](https://github.com/leduftw/playbook) v1. Change it there, not here; `playbook sync` brings this section back in line.

The facts about this repo live in `.github/playbook.toml`. Everything in this section is the same in every repo that follows the playbook.

### Every change

1. **Start from an issue.** Reuse the issue that describes the change, or create one assigned to `leduftw` with at least one label.
2. **Work in your own worktree.** Run `playbook start <issue>`: it creates `~/Developer/.worktrees/subtitler/<issue>-<slug>` on branch `dev/leduftw/<issue>-<slug>`, based on the latest `main`. Work only there. Another session may be working at the same time, so never edit the primary checkout; it stays on `main` and only moves with `git pull`.
3. **Commit and push** each finished slice to that branch, without pausing for confirmation.
4. **Open the PR** with `gh pr create --base main`. Its title becomes the commit on `main`, so it follows the commit style below. Put `Closes #<issue>` in the body when the PR fully resolves the issue.
5. **Land it with `playbook finish`.** It waits for the required checks, merges `main` into the branch if `main` has moved on, squash-merges, removes the worktree and the branch, pulls `main`, and confirms the issue is closed. If a check fails, fix it on the branch and run `playbook finish` again.

Sessions that don't change this repo's files (reading, planning, answering questions, running its tools) need no issue and no worktree.

**Never** commit or push to `main` (hooks and a GitHub ruleset refuse it), rebase a branch that's already pushed, or force-push. To catch up with `main`, merge it into your branch.

**Commit style:** start with a lowercase verb that says what the change does, then plain words, with no `feat:`-style prefix and no full stop. Names keep their capitals: `fix Windows installer replacement`, `add opt-in global leaderboard`. The `playbook / title` check rejects PR titles that break this.

**Without the `playbook` command** (a cloud session, a fresh machine), do the same by hand:

- start: `git fetch origin`, then `git worktree add -b dev/leduftw/<issue>-<slug> ~/Developer/.worktrees/subtitler/<issue>-<slug> origin/main` (a cloud session is already isolated, so a branch from `origin/main` is enough)
- finish: `gh pr checks --watch --required`, then `gh pr merge --squash`; once the PR shows `MERGED`, `git worktree remove <path>`, `git branch -D <branch>` (`-d` refuses, because squash commits aren't ancestors of `main`) and `git pull --ff-only` in the primary checkout

### Command-line tools

A command-line tool here follows the [Command Line Interface Guidelines](https://clig.dev) and the playbook's [rules for command-line tools](https://github.com/leduftw/playbook#how-command-line-tools-behave), in short:

- `-h`/`--help` print the help, which describes the tool with the repo's GitHub description, and `-V`/`--version` print exactly `<name> <version>`, both to stdout with exit 0. A tool with subcommands also takes `help [<command>]` and `version`.
- A wrong command, option or value prints a message to stderr and exits 2. A command that ran and failed exits 1.
- Started with no arguments at all, the tool does its default job. If something that job needs isn't set up yet (a token, a terminal), it prints the help plus one line saying what's missing, and exits 0. An explicit command still fails when its requirements are missing; an existing config that can't be read is an error either way.
- Help uses the colors of Python 3.14's `argparse`, only in a terminal, and none with `NO_COLOR`, `TERM=dumb` or `--no-color`.
- Arguments are parsed by the language's standard parser (`argparse`, `clap`, `System.CommandLine`), never by hand.

### Publishing

This repo is local: nothing is released. If that changes, the playbook adds the release setup (`published = true` and a `[release]` table in `.github/playbook.toml`).
<!-- playbook:end -->
