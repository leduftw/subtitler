#!/bin/sh
# Proves a standalone subtitler is fit to run other programs on someone else's
# machine: they mustn't inherit the libraries bundled inside it, and it must have
# found this machine's certificates. The release check runs it on every Unix build.
#
#   scripts/smoke-standalone.sh <path to the standalone subtitler>

set -eu

binary=$1
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Stand-ins for ffmpeg and ffprobe, so this tests what they're given, on machines
# that don't have them.
cat > "$work/ffprobe" <<'STUB'
#!/bin/sh
echo 60
STUB
cat > "$work/ffmpeg" <<'STUB'
#!/bin/sh
case ${LD_LIBRARY_PATH:-} in
  *subtitler-runtime-*)
    echo "ffmpeg inherited the bundled libraries: $LD_LIBRARY_PATH" >&2
    exit 1
    ;;
esac
if [ ! -f "${SSL_CERT_FILE:-}" ]; then
  echo "no certificates were found on this machine: SSL_CERT_FILE=${SSL_CERT_FILE:-}" >&2
  exit 1
fi
for last; do :; done
: > "$last"
STUB
chmod +x "$work/ffmpeg" "$work/ffprobe"

: > "$work/input.wav"
PATH="$work:$PATH" "$binary" "$work/input.wav" --dry-run --output "$work/output.srt"
