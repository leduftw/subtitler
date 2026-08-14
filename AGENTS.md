# Working agreements for this repo

## Commit and push regularly

**Commit each time a chunk of work is finished — don't leave work sitting
uncommitted across a session.** A "chunk" is anything that stands on its own: a
feature, a bug fix, a refactor, a docs update, a new test.

- Make small, logical commits rather than one large one. If a change touches code,
  tests, and docs for the same purpose, that's one commit; two unrelated fixes are
  two commits.
- Run `python3 -m unittest discover tests` before committing. Don't commit a red
  suite.
- Never commit secrets or media. API key files, `samples/`, `outputs/`, and
  `.work/` are gitignored on purpose — keep it that way.
- Don't commit generated `outputs/*.srt`; they are local artifacts.
- Keep `AGENTS.md` and `CLAUDE.md` byte-identical. The tracked
  `.githooks/pre-commit` hook enforces this when `core.hooksPath` is
  `.githooks`.

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
