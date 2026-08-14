# ai-subtitle-cli

Small CLI for generating `.srt` subtitles from a video or audio file.

It uses local `ffmpeg` to extract a clean speech audio track, then sends that audio to a transcription provider and writes SRT output. No UI, no database, no background service.

## Requirements

- Python 3.10+
- `ffmpeg` and `ffprobe` on `PATH`
- `AZURE_SPEECH_ENDPOINT` and `AZURE_SPEECH_API_KEY` for the Azure providers (`azure-fast`, `azure-hybrid`)
- `ELEVENLABS_API_KEY` for `scribe`

## Providers

Every provider produces word-level timing and speaker labels in sync with the audio.

| `--provider` | Model | Passes | Cost/min | Notes |
| --- | --- | --- | --- | --- |
| `scribe` (default) | ElevenLabs Scribe v2 | 1 | $0.0037 | Cheapest, lowest WER, best speaker separation |
| `azure-fast` | Azure fast transcription | 1 | $0.006 | No ElevenLabs account needed |
| `azure-hybrid` | MAI-1.5 text + fast timing | 2 | $0.012 | MAI's wording, for when it beats Scribe |

`scribe` is the default because it wins on every axis measured on a 3-minute
dialogue clip — most words captured, more than double the speaker turns, the
fewest cues blending two voices, and the lowest cost:

| | azure-fast | azure-hybrid | scribe |
| --- | --- | --- | --- |
| cues | 78 | 53 | 83 |
| speaker turns marked | 29 | 26 | **60** |
| words captured | 531 | 570 | **580** |
| cues merging two speakers | 3 | 3 | **1** |
| cost (3 min) | $0.018 | $0.036 | **$0.011** |

It also tops the independent
[Artificial Analysis leaderboard](https://artificialanalysis.ai/speech-to-text/non-streaming)
at 2.2% WER, against MAI's 2.4%. Use the Azure providers when you have no
ElevenLabs account, or for locales Scribe doesn't cover.

## Speaker labels (diarization)

Without speaker separation, an interruption collapses into nonsense — one person
says "But, I…" and the other cuts in with "You don't wanna do that", and the
subtitle reads `But I you don't wanna do that.`

Every provider identifies who is speaking, starts a new subtitle at each change of
speaker, and marks each turn with the standard `-` dialogue prefix:

```text
2
00:00:07,120 --> 00:00:08,340
- But, I

3
00:00:08,340 --> 00:00:09,900
- You don't wanna do that.
```

This is **on by default** — Azure bills diarization at no extra cost on fast
transcription, and a recording that turns out to have only one voice renders with
no prefixes at all, so there's nothing to lose.

```sh
# Turn it off:
./ai-subtitle "samples/example.mp4" --provider azure-fast --no-diarize

# Raise or lower the speaker ceiling (2-35, default 8):
./ai-subtitle "samples/example.mp4" --provider azure-fast --max-speakers 2
```

`--max-speakers 2` is worth setting for a two-person interview: a tighter bound
makes Azure less likely to split one voice across two speaker ids.

Diarization is not perfect. Where Azure gives both sides of an interruption the
same speaker id, the two still share one subtitle — expect a handful of these per
recording.

## Scribe Quick Start

```sh
export ELEVENLABS_API_KEY="..."

./ai-subtitle \
  --provider scribe \
  "samples/example.mp4" \
  --language en \
  --output "outputs/example.en.srt"
```

Scribe can also tag non-speech sounds, which is useful for accessibility subtitles:

```sh
./ai-subtitle --provider scribe "samples/example.mp4" --tag-audio-events
# ... produces cues like "(laughter)" and "(footsteps)"
```

For a dry run that extracts audio but calls no API:

```sh
./ai-subtitle \
  "samples/example.mp4" \
  --language en \
  --output "outputs/example.en.srt" \
  --dry-run
```

## Azure Quick Start

The Azure providers need an Azure Speech resource. With the
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

# Read the endpoint and key the CLI expects into the environment.
export AZURE_SPEECH_ENDPOINT="$(az cognitiveservices account show \
  --name "$SPEECH_RESOURCE" --resource-group "$RESOURCE_GROUP" \
  --query "properties.endpoint" --output tsv)"
export AZURE_SPEECH_API_KEY="$(az cognitiveservices account keys list \
  --name "$SPEECH_RESOURCE" --resource-group "$RESOURCE_GROUP" \
  --query "key1" --output tsv)"

# Sanity check (should print https://<resource>.cognitiveservices.azure.com/).
echo "$AZURE_SPEECH_ENDPOINT"

./ai-subtitle \
  --provider azure-fast \
  "samples/example.mp4" \
  --language en \
  --output "outputs/example.en.srt"
```

Azure accepts large uploads (500 MiB for `azure-fast`, 300 MiB for `azure-hybrid`):

```sh
./ai-subtitle \
  --provider azure-fast \
  "samples/example.mp4" \
  --audio-bitrate 48k \
  --output "outputs/example.srt"
```

### Best transcript wording: `azure-hybrid`

MAI-Transcribe-1.5 produces the most accurate text of any option here, but Azure
returns only coarse timing for it and can't diarize it at all — on its own it
collapses a whole recording into one enormous subtitle, which is why it isn't
offered as a `--provider` choice.

`azure-hybrid` makes it usable: it runs MAI for the text and Azure fast
transcription for word-level timing *and speakers*, then merges them so each line
appears as it's spoken and attributed to whoever said it. Same credentials, two
transcription passes (about 2× the cost).

```sh
./ai-subtitle \
  --provider azure-hybrid \
  "samples/example.mp4" \
  --language en \
  --output "outputs/example.en.srt"
```

### Languages MAI doesn't cover

MAI supports 43 languages; for anything outside that set, `azure-hybrid`
auto-detects and often produces wrong-language or mistimed output.

`scribe` covers 90+ languages and takes a plain ISO code, so it is the simplest
option:

```sh
./ai-subtitle "samples/example.mp4" --language es --output "outputs/example.es.srt"
```

`azure-fast` also covers many more locales than MAI, but wants a BCP-47 region
code (`es-ES`, `en-US`); bare codes like `es` are mapped for you:

```sh
./ai-subtitle \
  --provider azure-fast \
  "samples/example.mp4" \
  --language es-ES \
  --output "outputs/example.es.srt"
```

Run `./ai-subtitle --provider <name> --list-languages` for a provider's set.

## Translating subtitles

Transcription and translation are separate stages. No speech provider offers
translation *and* word-level timing *and* speakers in one call — Azure's LLM
Speech `translate` task drops both word offsets and diarization, and Scribe
doesn't translate at all. So translation runs over cues that are already
correctly timed, and only the text changes.

Translating cue by cue produces nonsense, because a sentence usually spans
several cues. Instead, the CLI writes a **worksheet** that groups cues into
speaker turns — so the translator reads whole sentences — while numbering every
line so the result reassembles onto the original timings.

```sh
# 1. Write the worksheet
./ai-subtitle outputs/film.sr.srt \
  --language sr --target-language en \
  --emit-worksheet work.txt

# 2. Translate the numbered lines in work.txt (see below)

# 3. Rebuild the subtitles on the original timings
./ai-subtitle outputs/film.sr.srt \
  --apply-worksheet work.txt \
  --target-language en \
  -o outputs/film.en.srt
```

Step 3 validates the numbering and refuses a worksheet that doesn't line up — a
single missing line would shift every later subtitle onto the wrong timestamp.

**There is no translation engine.** Step 2 is done by Claude, working through the
worksheet directly; the `.claude/skills/translate-subtitles` skill carries the
instructions for doing it well. That means translated files can't be regenerated
by rerunning the tool — keep the worksheet if the translation was expensive to
produce.

## Notes

- Default audio extraction is mono speech audio at `16 kHz` and `48k`, MP3. Diarization requires mono, which is what the pipeline already extracts.
- For very long files, lower `--audio-bitrate` to stay under the provider upload limit.
- Use `--language` when you know it; it improves accuracy and reduces language-detection ambiguity.
- Language hints use short codes. English is `en`, German is `de`, Spanish is `es`. Run `./ai-subtitle --list-languages` for the full supported language/code list.
- `azure-hybrid` inherits MAI's 43-language list, which is shorter than Whisper's. If you pass a `--language` it doesn't list, the CLI drops the hint and lets Azure auto-detect; run `./ai-subtitle --provider azure-hybrid --list-languages` to see its set.
- OpenAI is deliberately not supported. `whisper-1` is legacy (removed 2027-01-20), its replacement `gpt-transcribe` returns no timestamps at all, and `gpt-4o-transcribe-diarize` returns only speaker-turn segments — measured on a 3-minute clip, 7 of its 91 segments ran over 6 seconds with no word timings to split them. None of the three can produce well-timed subtitles.

## Tests

Standard library only, no test dependencies:

```sh
python3 -m unittest discover tests
```

## Documentation

See [docs/system.md](docs/system.md) for the architecture and implementation details.
