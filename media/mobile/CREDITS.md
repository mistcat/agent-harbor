# Credits: mobile clips' background track

The four MP4s in `media/mobile/` play a quiet bed of ocean waves under the panel's own sounds.

- **Title:** oceanwaves-10.wav (ocean waves recorded at Point Reyes, edited as a loop)
- **Artist:** Rmutt
- **Source:** https://freesound.org/people/Rmutt/sounds/156598/
- **License:** Creative Commons 0 (CC0 1.0 Universal, public domain dedication),
  https://creativecommons.org/publicdomain/zero/1.0/ (as stated on the source page)
- **Accessed:** 2026-11-16
- **Attribution:** not required by CC0. If you want a courtesy line: "Ocean waves: oceanwaves-10 by Rmutt (freesound.org, CC0)."

## The excerpt

`audio/oceanwaves-10-excerpt.m4a` is 28 s (longer than any clip) of Freesound's public HQ preview of the
recording (the original WAV download needs a login; the preview is enough for a bed this quiet), starting at
15 s, the steadiest 28 s stretch by short-term loudness. Made with:

```bash
curl -sLO https://cdn.freesound.org/previews/156/156598_981371-hq.mp3
ffmpeg -ss 15 -t 28 -i 156598_981371-hq.mp3 -c:a aac -b:a 128k -threads 1 \
  -fflags +bitexact -flags:a +bitexact -map_metadata -1 oceanwaves-10-excerpt.m4a
```

`scripts/make_harbor_gifs.py --mobile` mixes it at `BED_DB` (about -28 LUFS), fades it in and out over a
second, and ducks it a further `DUCK_DB` (12 dB) from 1.5 s before each cannon or ahoy until 1 s after it.
In attention-call the duck after the boom holds until the ahoy's own duck begins (`DUCK_HOLD`, 19.5 s), so
the waves stay low from the boom to the ahoy.
Each clip plays the excerpt from its start, except advisor-call, which starts 5 s in (`BED_OFFSET`) so no
swell breaks next to a cannon.
