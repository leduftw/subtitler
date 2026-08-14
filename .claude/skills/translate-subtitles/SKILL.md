---
name: translate-subtitles
description: Translate an .srt subtitle file into another language while keeping its exact timings and speaker labels. Claude does the translating personally — there is no translation API involved, and none should be added. Use this skill whenever the user wants subtitles in a different language, asks for English/German/Spanish/etc. subtitles for foreign-language media, mentions translating a transcript or a subtitle file, or has just generated an .srt and wants a second language version of it. Also use it when the user says something like "can you translate this film" or "I need English subs for this" even if they never say the word "subtitle" or "srt".
---

# Translating subtitles

Translate an existing `.srt` into another language, keeping every timestamp
exactly as it was. Only the text changes. You are the translator — no machine
translation service is called at any point, which is the whole reason this
workflow exists.

## Why not just translate the file directly

Two obvious approaches both fail, and knowing why keeps you from drifting back
into them.

**Translating cue by cue produces nonsense.** Cues are split for reading speed,
not for meaning, so one sentence routinely spans three of them:

```text
y gracias por venir a esta reunión que,
como ya saben, hemos aplazado
tres veces.
```

The last line means nothing on its own. Translated in isolation, each fragment
comes out grammatically stranded.

**Translating the merged paragraph can't be mapped back.** If you join the cues,
translate the paragraph, and then try to redistribute it, there is nothing to
align on — a translation shares no words with its source. (This is exactly why
`align.py` in this repo cannot help: it works only because both of its inputs are
the same language.)

The worksheet solves both. Cues are grouped into speaker turns so you read whole
sentences, and every line keeps a number so your translation reassembles onto the
original timings.

## The workflow

Three steps. Steps 1 and 3 are commands; step 2 is you.

### 1. Emit the worksheet

```sh
./ai-subtitle <source.srt> \
  --language <source-lang> \
  --target-language <target-lang> \
  --emit-worksheet <worksheet.txt>
```

Write the worksheet somewhere durable if the translation is large — your
scratchpad is session-scoped, and losing a long translation means redoing it by
hand.

### 2. Translate the worksheet

Read the whole file first, then write the translation. The output must have the
same numbered lines as the input.

For anything longer than a few hundred lines, write the translation in chunks to
separate files and concatenate them at the end — a single enormous write is where
lines get dropped:

```sh
cat chunk_01.txt chunk_02.txt chunk_03.txt > translated.txt
```

Header comment lines (`#`) and `[SPEAKER]` headers do not need to be reproduced;
only the numbered lines are read back.

### 3. Apply it

```sh
./ai-subtitle <source.srt> \
  --apply-worksheet <translated.txt> \
  --target-language <target-lang> \
  -o <output.srt>
```

This validates the numbering and refuses a worksheet that doesn't line up, rather
than guessing. A single missing line would shift every later subtitle onto the
wrong timestamp — the kind of failure you only notice forty minutes into a film.

## Rules for the translation itself

These are what the output is judged on.

**Keep every line number, exactly once, in order.** Never merge two lines into
one, split one into two, drop a line, add a line, or renumber. The count in
equals the count out.

**Read the whole `[SPEAKER]` block before translating any line in it.** Work out
the complete sentences, translate them properly, then redistribute across the
same numbered lines at natural phrase boundaries.

**A line may end mid-sentence. Leave it that way.** Do not "complete" a fragment
to make it read well alone — the next line continues it.

**Keep a leading `- `.** It marks a change of speaker and the renderer relies on
it.

**Match the register, don't improve it.** If the source is street slang, the
translation is street slang. If it is crude, it stays crude — sanitising profanity
misrepresents the speaker. If it is formal, keep it formal. Flattening a
distinctive voice into neutral prose is the most common way this goes wrong.

**Translate what was said, not what was meant.** If the speaker is cut off
mid-word, the translation is cut off too. If a number or name looks like a
transcription error, keep it as written rather than silently correcting it —
mention it to the user afterwards instead.

**Garbled input stays garbled.** Sung lyrics in particular often come back from
speech recognition as near-nonsense. Translate them as faithfully as the source
allows; inventing coherent lyrics fabricates content that isn't in the film.

**No translator's notes, no explanations, no bracketed glosses** in the lines
themselves. Anything you want to flag goes in your reply to the user.

## Verifying

The apply step reports the cue count. Confirm it matches the source, and confirm
the timings survived:

```sh
python3 - <<'PY'
import sys; sys.path.insert(0, "src")
from pathlib import Path
from ai_subtitle_cli.srt import parse_srt
a = parse_srt(Path("<source.srt>").read_text(encoding="utf-8"))
b = parse_srt(Path("<output.srt>").read_text(encoding="utf-8"))
print("cues:", len(a), "->", len(b))
print("timings identical:", [(c.start_ms, c.end_ms) for c in a] == [(c.start_ms, c.end_ms) for c in b])
PY
```

Then spot-check a passage in the middle of the file, not just the opening.

## Reporting back

Tell the user what you translated, and be specific about anything you could not
do well: passages where the source transcription was too garbled to translate
faithfully, apparent transcription errors you preserved rather than corrected,
and any place where you had to guess at meaning. A translation that quietly
smooths over broken input is worse than one that says where it is unreliable.

Say plainly that you did the translation yourself. Users reasonably assume a
translation engine was involved, and the distinction matters: these files cannot
be regenerated by running the tool.

## Worked example

Source worksheet:

```text
[A] 00:00:16,280
1| - Buenos días a todos,
2| y gracias por venir a esta reunión que, como ya saben, hemos aplazado
3| tres veces.
```

Translated worksheet:

```text
1| - Good morning, everyone,
2| and thank you for coming to this meeting which, as you already know, we have postponed
3| three times.
```

Line 3 is still a fragment, and still lands on its original 1.07-second cue.
