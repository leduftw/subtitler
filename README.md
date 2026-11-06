# subtitler

[![CI](https://github.com/leduftw/subtitler/actions/workflows/playbook.yml/badge.svg)](https://github.com/leduftw/subtitler/actions/workflows/playbook.yml)
[![Latest release](https://img.shields.io/github/v/release/leduftw/subtitler)](https://github.com/leduftw/subtitler/releases/latest)

Subtitles for any video, in any language.

Point it at a video or audio file and it writes an `.srt`: who said what, when
they said it, and — if you ask — translated into whatever language you need.

It works two ways. Run it yourself as a command, or just ask a coding agent
(Claude Code, Codex, or similar) to do it for you — *"make me English subtitles
for this film"* is enough. The agent runs the commands and handles the translation
stage itself. You don't have to know what an SRT is.

Under the hood: local `ffmpeg` extracts a clean speech track, that audio (and only
that audio — never the video) goes to a transcription provider, and the result is
assembled into subtitles locally. No UI, no database, no background service.

## Install

```sh
brew install leduftw/tap/subtitler   # Homebrew on macOS or Linux; brings ffmpeg along
winget install leduftw.subtitler     # Windows
uv tool install leduftw-subtitler    # PyPI, with Python 3.10 or newer
```

`pipx install leduftw-subtitler` and `pip install leduftw-subtitler` work too. On
PyPI the package has a longer name because `subtitler` belongs to an unrelated
project; the command is `subtitler` either way.

Each release is submitted to Microsoft's moderated WinGet repository, so a new
version can take a while to appear there.

Or use the one-line installer, which picks the build for your machine, checks it
against the release's `SHA256SUMS` and installs it without `sudo`:

```sh
curl -fsSL https://github.com/leduftw/subtitler/releases/latest/download/subtitler-installer.sh | sh
```

```powershell
irm https://github.com/leduftw/subtitler/releases/latest/download/subtitler-installer.ps1 | iex
```

Set `SUBTITLER_VERSION` to install a specific version or `SUBTITLER_INSTALL_DIR` to
choose the destination. If the destination isn't on `PATH`, the installer prints the
line to add.

Every release also ships standalone programs for macOS, Linux and Windows, each for
both Arm and Intel/AMD chips, with stable names such as `subtitler-macos-arm64.zip`.
They carry their own Python. Grab the archive for your platform from the
[latest release](https://github.com/leduftw/subtitler/releases/latest), extract it,
and run `subtitler`, keeping the `subtitler-runtime-<version>` folder beside it. macOS
checks a new program the first time it runs, which takes a couple of seconds once.
If macOS Gatekeeper blocks a browser-downloaded program, clear the quarantine flag in
the extracted folder with `xattr -dr com.apple.quarantine .`.

### Requirements

- `ffmpeg` and `ffprobe` on `PATH`. Homebrew installs them for you; elsewhere, use
  `winget install Gyan.FFmpeg` on Windows or your system's package manager on Linux.
- `AZURE_SPEECH_ENDPOINT` and `AZURE_SPEECH_API_KEY` for the Azure providers (`azure-mai-2`, `azure-fast`, `azure-hybrid`)
- `ELEVENLABS_API_KEY` for `scribe`

### Updating

`subtitler update` (or `upgrade`) checks for a newer release and installs it the same
way subtitler was installed: `brew upgrade leduftw/tap/subtitler` for Homebrew,
`winget upgrade --id leduftw.subtitler` for WinGet, `uv tool upgrade`, `pipx upgrade`
or `pip install --upgrade` for PyPI, and the one-line installer again, into the same
folder, for everything else. A new version reaches WinGet only after Microsoft's
review, so until it does, `subtitler update` says the release isn't on WinGet yet.
A clone isn't updated this way; use `git pull` instead.

### Run from a clone

With Python 3.10 or newer, no install step and no dependencies:

```sh
git clone https://github.com/leduftw/subtitler.git
cd subtitler
./subtitler --help
```

That launcher is a shell script. In PowerShell or `cmd`, run `pip install .` from the
clone instead, which gives you the `subtitler` command.

## Usage

### Command line

`subtitler --help` (or `-h`, or `help`) lists every command and option, and `subtitler --version`
(or `-V`, or `version`) prints the version. Run with no arguments at all, it prints
the same help and what it needs: a video or audio file. The help is colored only in
a terminal; `--no-color`, `NO_COLOR` or `TERM=dumb` turn the colors off.

`help`, `version`, `update` and `upgrade` are commands when they come first. To read
a file with one of those names, write `./help`.

A mistake on the command line, such as an unknown option or a file that isn't
there, exits 2. A failure while running, such as a missing `ffmpeg` or a
provider error, exits 1.

### Providers

Every provider produces word-level timing and speaker labels in sync with the audio.

| `--provider` | Model | Passes | Cost/min | Cost/hour | Notes |
| --- | --- | --- | --- | --- | --- |
| `scribe` (default) | ElevenLabs Scribe v2 | 1 | $0.0037 | $0.22 | Broad language coverage, word timing and speakers |
| `azure-mai-2` | MAI-Transcribe-2 | 1 | $0.006 | $0.36 | Native word timing and speakers; preview limits below |
| `azure-fast` | Azure fast transcription | 1 | $0.006 | $0.36 | No ElevenLabs account needed |
| `azure-hybrid` | MAI-1.5 text + fast timing | 2 | $0.012 | $0.72 | Cleaner text than `azure-fast`, at 2× its cost |

These are the rates used for the estimate printed before upload. The
`azure-mai-2` estimate uses the standard Azure rate conservatively; Microsoft's
[introductory offer](https://microsoft.ai/news/mai-transcribe-2-is-the-fastest-most-accurate-and-cheapest-speech-recognition-model-in-the-world/)
is $0.10/hour through December 31, 2026, so the actual bill may be lower.

`scribe` remains the default. As of November 6, 2026, the independent
[Artificial Analysis leaderboard](https://artificialanalysis.ai/speech-to-text/non-streaming)
reports 2.0% WER for MAI-Transcribe-2 and 2.2% for Scribe v2. That is a useful
reason to compare `azure-mai-2` on your recordings, rather than a guarantee of
better subtitles for every film or language. Scribe covers more languages;
MAI-Transcribe-2 does not support Serbian or Croatian.

### Speaker labels (diarization)

Without speaker separation, an interruption collapses into nonsense — one person
says "Sorry, I…" and the other cuts in with "You don't need to apologize", and
the subtitle reads `Sorry I you don't need to apologize.`

Every provider identifies who is speaking, starts a new subtitle at each change of
speaker, and marks each turn with the standard `-` dialogue prefix:

```text
2
00:00:07,120 --> 00:00:08,340
- Sorry, I

3
00:00:08,340 --> 00:00:09,900
- You don't need to apologize.
```

This is **on by default**. Azure fast transcription includes diarization, and a
recording with only one voice renders with no prefixes. MAI-Transcribe-2 has a
preview limitation: diarization can fail on longer recordings, including reports
around 15 minutes. Use `--no-diarize` or another provider for long files; subtitler
does not silently remove speaker labels and retry.

```sh
# Turn it off:
subtitler "video.mp4" --provider azure-fast --no-diarize

# Raise or lower the speaker ceiling (2-35, default 8):
subtitler "video.mp4" --provider azure-fast --max-speakers 2
```

`--max-speakers 2` is worth setting for a two-person interview: a tighter bound
makes Azure less likely to split one voice across two speaker ids.
`azure-mai-2` does not support `--max-speakers`; its speaker count is automatic.

Diarization is not perfect. Where Azure gives both sides of an interruption the
same speaker id, the two still share one subtitle — expect a handful of these per
recording.

### Scribe Quick Start

```sh
export ELEVENLABS_API_KEY="..."

subtitler \
  --provider scribe \
  "video.mp4" \
  --language en \
  --output "video.en.srt"
```

Scribe can also tag non-speech sounds, which is useful for accessibility subtitles:

```sh
subtitler --provider scribe "video.mp4" --tag-audio-events
# ... produces cues like "(laughter)" and "(footsteps)"
```

For a dry run that extracts audio but calls no API:

```sh
subtitler \
  "video.mp4" \
  --language en \
  --output "video.en.srt" \
  --dry-run
```

### Azure Quick Start

The Azure providers share the same credentials and need an Azure Speech resource.
For `azure-mai-2`, choose a
[supported region](https://learn.microsoft.com/azure/ai-services/speech-service/regions),
such as North Europe. With the
[Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
installed, you can read its endpoint and key straight into the environment:

```sh
# Sign in (opens a browser).
az login

# List your Speech resources, then copy the name + resource group of the one to use.
az cognitiveservices account list \
  --query "[?kind=='SpeechServices' || kind=='AIServices'].{name:name, resourceGroup:resourceGroup, kind:kind, endpoint:properties.endpoint}" \
  --output table

# Fill these two in from the table above.
RESOURCE_GROUP="<your-resource-group>"
SPEECH_RESOURCE="<your-resource-name>"

# Read the endpoint and key subtitler expects into the environment.
export AZURE_SPEECH_ENDPOINT="$(az cognitiveservices account show \
  --name "$SPEECH_RESOURCE" --resource-group "$RESOURCE_GROUP" \
  --query "properties.endpoint" --output tsv)"
export AZURE_SPEECH_API_KEY="$(az cognitiveservices account keys list \
  --name "$SPEECH_RESOURCE" --resource-group "$RESOURCE_GROUP" \
  --query "key1" --output tsv)"

# Sanity check (should print https://<resource>.cognitiveservices.azure.com/).
echo "$AZURE_SPEECH_ENDPOINT"

subtitler \
  --provider azure-fast \
  "video.mp4" \
  --language en \
  --output "video.en.srt"
```

If you need a new Speech resource, choose a globally unique resource name and
create it in your resource group before reading the endpoint and key above:

```sh
az cognitiveservices account create \
  --resource-group "$RESOURCE_GROUP" --name "$SPEECH_RESOURCE" \
  --kind SpeechServices --sku S0 --location northeurope \
  --custom-domain "$SPEECH_RESOURCE"
```

The default upload caps are 238 MiB for `azure-mai-2`, 500 MiB for `azure-fast`,
and 300 MiB for `azure-hybrid`. Lowering bitrate can reduce upload size:

```sh
subtitler \
  --provider azure-fast \
  "video.mp4" \
  --audio-bitrate 48k \
  --output "video.srt"
```

#### Native MAI-Transcribe-2: `azure-mai-2`

MAI-Transcribe-2 returns its own word-level timestamps and optional speaker labels
in one request. It needs no hybrid alignment pass:

```sh
subtitler \
  --provider azure-mai-2 \
  "video.mp4" \
  --language en \
  --output "video.en.srt"
```

The default `--azure-transcribe-style display` requests MAI-2's `clean` style,
which removes fillers and formats speech for readability. Use
`--azure-transcribe-style verbatim` to preserve fillers and false starts.
`--azure-model` applies only to the older `azure-hybrid` text pass; `azure-mai-2`
always selects MAI-Transcribe-2.

This Azure API is in preview. Native diarization can fail on longer recordings
(reported from around 15 minutes); see the
[Microsoft discussion](https://learn.microsoft.com/answers/questions/5995065/mai-transcribe-2-speaker-diarization-fails-on-reco).
For long files, use `--no-diarize` to keep MAI-2's text and timing without speaker
labels, or choose `scribe` or `azure-fast`. A failed request is reported as an
error; the tool never silently changes the requested provider or diarization.
Microsoft's REST reference also limits one request to audio shorter than 2 hours,
and subtitler sends the whole file at once, so use `scribe` for longer recordings.

MAI-2 supports 60 languages. Run
`subtitler --provider azure-mai-2 --list-languages` for the exact codes. An
unsupported explicit hint, including `sr` or `hr`, exits 2 before upload; omit
the hint only for audio in one of the supported languages when you want
auto-detection.

#### Older MAI-1.5 with Azure timing: `azure-hybrid`

MAI-Transcribe-1.5 is Azure's LLM transcription mode, and it writes cleaner text
than plain fast transcription does. Unlike MAI-2, version 1.5 returns only coarse
timing and cannot diarize — on its own it collapses a whole recording into one
enormous subtitle, which is why it isn't offered as a `--provider` choice.

`azure-hybrid` makes version 1.5 usable: it runs MAI for the text and Azure fast
transcription for word-level timing *and speakers*, then merges them so each line
appears as it's spoken and attributed to whoever said it. Same credentials, two
transcription passes (about 2× the cost).

The hybrid remains available for existing workflows. For MAI-2's newer text
model and native timing, choose `azure-mai-2` instead; neither path removes the
need to review difficult dialogue.

```sh
subtitler \
  --provider azure-hybrid \
  "video.mp4" \
  --language en \
  --output "video.en.srt"
```

#### Languages MAI doesn't cover

MAI-1.5 supports 43 languages; for anything outside that set, `azure-hybrid`
auto-detects and often produces wrong-language or mistimed output.

`scribe` covers 90+ languages and takes a plain ISO code, so it is the simplest
option:

```sh
subtitler "video.mp4" --language es --output "video.es.srt"
```

`azure-fast` also covers many more locales than MAI-1.5, but wants a BCP-47 region
code (`es-ES`, `en-US`); bare codes like `es` are mapped for you:

```sh
subtitler \
  --provider azure-fast \
  "video.mp4" \
  --language es-ES \
  --output "video.es.srt"
```

Run `subtitler --provider <name> --list-languages` for a provider's set.

### Translating subtitles

Transcription and translation are separate stages. No speech provider offers
translation *and* word-level timing *and* speakers in one call — Azure's LLM
Speech `translate` task drops both word offsets and diarization, and Scribe
doesn't translate at all. So translation runs over cues that are already
correctly timed, and only the text changes.

Translating cue by cue produces nonsense, because a sentence usually spans
several cues. Instead, `subtitler` writes a **worksheet** that groups cues into
speaker turns — so the translator reads whole sentences — while numbering every
line so the result reassembles onto the original timings.

```sh
# 1. Write the worksheet
subtitler film.es.srt \
  --language es --target-language en \
  --emit-worksheet work.txt

# 2. Translate the numbered lines in work.txt (see below)

# 3. Rebuild the subtitles on the original timings
subtitler film.es.srt \
  --apply-worksheet work.txt \
  --target-language en \
  -o film.en.srt
```

Step 3 validates the numbering and refuses a worksheet that doesn't line up — a
single missing line would shift every later subtitle onto the wrong timestamp.

**There is no translation engine, by design.** Step 2 is done by the agent
itself, working through the worksheet directly. `subtitler --translation-guide`
prints the instructions for doing it well, and the worksheet and `--help` both point
an agent at them, so any agent can follow them on an installed copy. In a clone,
the `.claude/skills/translate-subtitles` skill hands Claude Code the same guide.
Machine translation flattens the register of ordinary speech; an agent that can read
the whole scene keeps the slang, the tone and the interruptions intact.

The practical consequence: a translated file can't be regenerated by rerunning
the tool. Keep the worksheet if the translation was expensive to produce.

If you are driving this through an agent, you don't need to run any of the above
by hand — ask for the language you want and it will do all three steps.

### Notes

- Pass `--output` to say where the `.srt` goes. Without it, the run writes to `outputs/<input-stem>.<language-or-auto>.srt` under the current directory, creating that directory if needed.
- Default audio extraction is mono speech audio at `16 kHz` and `48k`, MP3. Diarization requires mono, which is what the pipeline already extracts.
- For very long files, lower `--audio-bitrate` to stay under the provider upload limit.
- Use `--language` when you know it; it improves accuracy and reduces language-detection ambiguity.
- Language hints use short codes. English is `en`, German is `de`, Spanish is `es`. Run `subtitler --list-languages` for the full supported language/code list.
- `azure-hybrid` inherits MAI's 43-language list, which is shorter than Whisper's. If you pass a `--language` it doesn't list, `subtitler` drops the hint and lets Azure auto-detect; run `subtitler --provider azure-hybrid --list-languages` to see its set.
- `azure-mai-2` has a separate 60-language list and rejects unsupported hints. Its native diarization is unsuitable for some long recordings in the current preview; use `--no-diarize` or another provider when needed.
- OpenAI is deliberately not supported. `whisper-1` is legacy (removed 2027-01-20), its replacement `gpt-transcribe` returns no timestamps at all, and `gpt-4o-transcribe-diarize` returns only speaker-turn segments — measured on a 3-minute clip, 7 of its 91 segments ran over 6 seconds with no word timings to split them. None of the three can produce well-timed subtitles.

## Development

subtitler is plain Python with no dependencies beyond the standard library, and
neither do its tests:

```sh
python3 -m unittest discover tests
```

See [docs/system.md](https://github.com/leduftw/subtitler/blob/main/docs/system.md) for the architecture and implementation details.

## License

[MIT](https://github.com/leduftw/subtitler/blob/main/LICENSE)
