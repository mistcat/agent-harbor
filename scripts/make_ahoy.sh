#!/usr/bin/env bash
# Build the panel's "ahoy" attention call: a deep, dry, gravelly "Ah-hoy ... may-tee".
# Run: scripts/make_ahoy.sh [OUT]   (default: agent_panel/assets/ahoy.wav)
#
# Needs macOS `say` with the Daniel voice, and ffmpeg. Each word is spoken by Daniel, trimmed, pitched
# down, bass-boosted and lightly bit-crushed; the two are sped up (pitch kept, "may-tee" faster than "Ah-hoy"),
# joined with a short gap and limited.
# `say` output can differ slightly between macOS versions, so the committed ahoy.wav is the approved take.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
out="${1:-$root/agent_panel/assets/ahoy.wav}"
[[ "$out" = /* ]] || out="$PWD/$out"  # resolve before we cd into the temp dir
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"

seg() { # out rate text
  say -v Daniel -r "$2" -o "$1.aiff" "$3" 2>/dev/null && ffmpeg -y -loglevel error -i "$1.aiff" -af "silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=1:stop_threshold=-45dB:stop_duration=0.05,asetrate=22050*0.78,aresample=44100,atempo=1.282,bass=g=12:f=110:w=0.8,acrusher=bits=10:mode=log:aa=1:mix=0.5,volume=1.6,aformat=sample_rates=44100:channel_layouts=mono" "$1.wav"; }
join() { # name seg1 tempo1 seg2 tempo2 gap
  ffmpeg -y -loglevel error -i "$2.wav" -f lavfi -t "$6" -i "anullsrc=r=44100:cl=mono" -i "$4.wav" -filter_complex "[0:a]atempo=$3[a];[2:a]atempo=$5[b];[a][1:a][b]concat=n=3:v=0:a=1,alimiter=limit=0.9" "$1.wav"; }
seg s1 150 "Ah-hoy"; seg s2 150 "may-tee"; join ahoy s1 1.4 s2 1.75 0.07

mv ahoy.wav "$out"
echo "wrote $out"
