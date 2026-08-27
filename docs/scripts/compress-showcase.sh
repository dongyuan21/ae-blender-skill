#!/usr/bin/env bash
# Compress original showcase media into GitHub-friendly 480-wide / 15fps assets.
# Covers the top-right brand mark on portrait gameplay frames.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/notes/archives/ae-reference-stack-layout-render"
OUT="$ROOT/docs/assets/ae-reference-stack-layout-render"

BEFORE_SRC="$SRC/iwEcAqNtcDQDAQQABQAGsF7b4JN-ydioCmJqhBhr9wEH0wAAAAGS9zueCAAJomltCgAL0gD68Cs.mp4"
AFTER_SRC="$SRC/iwEcAqNtcDQDAQQABQAGsFm1i2hWGZfbCmJqhBuFYgAH0wAAAAGS9zueCAAJomltCgAL0gEGg9Y.mp4"

if command -v ffmpeg >/dev/null 2>&1; then
  FFMPEG="$(command -v ffmpeg)"
else
  FFMPEG="$(python3 -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')"
fi

mkdir -p "$OUT"

# Source frames are 406x720. Cover the top-right brand before scaling.
COVER="delogo=x=268:y=1:w=136:h=110:show=0"
SCALE_FULL="scale='min(480,iw)':-2:flags=lanczos"
SCALE_GIF="fps=10,scale=360:-2:flags=lanczos"

encode_mp4() {
  local input="$1"
  local output="$2"
  "$FFMPEG" -y -i "$input" \
    -vf "${COVER},${SCALE_FULL},fps=15" \
    -c:v libx264 -profile:v high -pix_fmt yuv420p -crf 28 -preset slow \
    -c:a aac -b:a 64k -ac 2 \
    -movflags +faststart \
    "$output"
}

echo "==> before.mp4"
encode_mp4 "$BEFORE_SRC" "$OUT/before.mp4"

echo "==> after.mp4"
encode_mp4 "$AFTER_SRC" "$OUT/after.mp4"

echo "==> comparison.mp4"
"$FFMPEG" -y -i "$BEFORE_SRC" -i "$AFTER_SRC" \
  -filter_complex "[0:v]${COVER},${SCALE_FULL},fps=15,setsar=1[left];[1:v]${COVER},${SCALE_FULL},fps=15,setsar=1[right];[left][right]hstack=inputs=2:shortest=1[v]" \
  -map "[v]" -map 0:a? \
  -c:v libx264 -profile:v high -pix_fmt yuv420p -crf 28 -preset slow \
  -c:a aac -b:a 64k -ac 2 \
  -movflags +faststart \
  "$OUT/comparison.mp4"

make_gif() {
  local input="$1"
  local output="$2"
  "$FFMPEG" -y -t 6 -i "$input" \
    -vf "${COVER},${SCALE_GIF},split[s0][s1];[s0]palettegen=max_colors=128:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3" \
    "$output"
}

echo "==> before.gif"
make_gif "$BEFORE_SRC" "$OUT/before.gif"

echo "==> after.gif"
make_gif "$AFTER_SRC" "$OUT/after.gif"

echo "==> stills"
"$FFMPEG" -y -i "$SRC/reference_09.png" -q:v 4 "$OUT/reference.jpg"
"$FFMPEG" -y -i "$SRC/reference-vs-clean-render.png" \
  -vf "delogo=x=930:y=4:w=146:h=124:show=0" \
  -q:v 4 "$OUT/reference-vs-render.jpg"

"$FFMPEG" -y -ss 3 -i "$OUT/before.mp4" -frames:v 1 -update 1 -q:v 4 "$OUT/poster-before.jpg"
"$FFMPEG" -y -ss 3 -i "$OUT/after.mp4" -frames:v 1 -update 1 -q:v 4 "$OUT/poster-after.jpg"

echo "==> done"
ls -lh "$OUT"
