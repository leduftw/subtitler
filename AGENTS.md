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
or an SDK. Adding a dependency needs a real justification. PyInstaller doesn't count:
it runs only in the release build.

## Architecture invariants

- Providers return `list[Cue]`, never formatted SRT text. Rendering, line wrapping,
  and speaker labelling happen once in `srt.py`.
- A cue must never span two speakers. That guarantee lives in
  `group_words_into_cues`, not in individual providers.
- A provider whose `SPEC` sets `internal=True` stays registered and reusable but is
  hidden from `--provider` choices (this is how `azure-mai` survives as
  `azure-hybrid`'s text pass without being user-selectable).
- The translation instructions have one source, `src/subtitler/translation_guide.md`,
  which ships with every install and prints with `--translation-guide`. The repo's
  `translate-subtitles` skill only points at it. The guide can't assume a clone or a
  Python, because a standalone install has neither.
- Installed copies can't see the repository: a file read at run time must be package
  data listed in `pyproject.toml`.
- `help`, `version`, `update` and `upgrade` are commands only as the first word of a
  command line, so `./help` still reaches a file. Adding a word takes that name from
  people's files, so an action that needs no word of its own is a flag instead, like
  `--list-languages` and `--translation-guide`.

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
- `update` (alias `upgrade`) moves to the latest release through whatever installed the tool: `brew upgrade`, `winget upgrade`, `cargo install`, `dotnet tool update`, or the release's own installer.
- Every release PR checks these rules against the real binaries on all six platforms, so a release that breaks them doesn't ship.

### Releasing

This repo is published: other people install it.

- `playbook release patch|minor|major` opens a PR that only bumps the version; nobody types a version number. The first release is always 1.0.0, and every later one is exactly the next patch, minor or major.
- That PR builds and smoke-tests every release file on all six platforms. Landing it with `playbook finish` tags the release, publishes it on GitHub Releases and updates the Homebrew tap, WinGet, the one-line installers and PyPI.
- A published release is locked. A broken one is never fixed in place; ship the next patch.
- If a channel fails (an expired token, a WinGet outage), fix the cause, then run `gh workflow run playbook --ref main`. A manual run whose version matches the latest release updates only its channels, from the files already published.
<!-- playbook:end -->
