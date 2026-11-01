---
name: translate-subtitles
description: Translate an .srt subtitle file into another language while keeping its exact timings and speaker labels. Claude does the translating personally — there is no translation API involved, and none should be added. Use this skill whenever the user wants subtitles in a different language, asks for English/German/Spanish/etc. subtitles for foreign-language media, mentions translating a transcript or a subtitle file, or has just generated an .srt and wants a second language version of it. Also use it when the user says something like "can you translate this film" or "I need English subs for this" even if they never say the word "subtitle" or "srt".
---

# Translating subtitles

The instructions ship with subtitler, so an installed copy has them too. From the
root of this repository, run this and follow what it prints:

```sh
./subtitler --translation-guide
```

To change them, edit `src/subtitler/translation_guide.md`.
