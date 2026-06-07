#!/usr/bin/env bash
#
# Re-encode portfolio GIFs for the web.
#
# GIF animations compress poorly. This script generates much smaller MP4 and
# WebM files (recommended for <video> tags) and can optionally try to shrink
# the GIF itself when ffmpeg produces a smaller file.
#
# Requirements: ffmpeg
#
# Usage:
#   ./scripts/reencode-gifs.sh
#   ./scripts/reencode-gifs.sh --dir photos --output-dir photos/reencoded
#   ./scripts/reencode-gifs.sh --gif --replace-gif
#   ./scripts/reencode-gifs.sh --dry-run
#
# After running, swap <img src="...gif"> for:
#   <video autoplay loop muted playsinline width="W" height="H" loading="lazy">
#     <source src="photos/name.webm" type="video/webm">
#     <source src="photos/name.mp4" type="video/mp4">
#   </video>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

INPUT_DIR="${ROOT_DIR}/photos"
OUTPUT_DIR="${ROOT_DIR}/photos/reencoded"
ENCODE_GIF=0
REPLACE_GIF=0
DRY_RUN=0
CRF_MP4=23
CRF_WEBM=32

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  echo
  echo "Options:"
  echo "  --dir PATH          Directory to scan for GIFs (default: photos/)"
  echo "  --output-dir PATH   Where to write MP4/WebM/GIF output (default: photos/reencoded/)"
  echo "  --gif               Also attempt a palette-optimized GIF"
  echo "  --replace-gif       Replace source GIF when optimized GIF is smaller (backs up to .bak)"
  echo "  --crf-mp4 N         H.264 quality, lower is better (default: 23)"
  echo "  --crf-webm N        VP9 quality, lower is better (default: 32)"
  echo "  --dry-run           Print commands without encoding"
  echo "  -h, --help          Show this help"
}

log() {
  printf '==> %s\n' "$*"
}

human_size() {
  local bytes="$1"
  if (( bytes >= 1073741824 )); then
    printf '%.1fG' "$(awk "BEGIN { print ${bytes} / 1073741824 }")"
  elif (( bytes >= 1048576 )); then
    printf '%.1fM' "$(awk "BEGIN { print ${bytes} / 1048576 }")"
  elif (( bytes >= 1024 )); then
    printf '%.1fK' "$(awk "BEGIN { print ${bytes} / 1024 }")"
  else
    printf '%sB' "${bytes}"
  fi
}

require_ffmpeg() {
  if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "ffmpeg is required. Install with: brew install ffmpeg" >&2
    exit 1
  fi
}

even_dimensions_filter() {
  printf 'scale=trunc(iw/2)*2:trunc(ih/2)*2'
}

encode_mp4() {
  local input="$1"
  local output="$2"
  local vf
  vf="$(even_dimensions_filter)"

  ffmpeg -hide_banner -loglevel error -y \
    -i "${input}" \
    -an \
    -movflags +faststart \
    -pix_fmt yuv420p \
    -vf "${vf}" \
    -c:v libx264 \
    -crf "${CRF_MP4}" \
    -preset slow \
    "${output}"
}

encode_webm() {
  local input="$1"
  local output="$2"
  local vf
  vf="$(even_dimensions_filter)"

  ffmpeg -hide_banner -loglevel error -y \
    -i "${input}" \
    -an \
    -pix_fmt yuv420p \
    -vf "${vf}" \
    -c:v libvpx-vp9 \
    -crf "${CRF_WEBM}" \
    -b:v 0 \
    -row-mt 1 \
    "${output}"
}

encode_optimized_gif() {
  local input="$1"
  local output="$2"

  ffmpeg -hide_banner -loglevel error -y \
    -i "${input}" \
    -vf "split[s0][s1];[s0]palettegen=max_colors=256:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3" \
    -loop 0 \
    "${output}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      INPUT_DIR="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --gif)
      ENCODE_GIF=1
      shift
      ;;
    --replace-gif)
      REPLACE_GIF=1
      ENCODE_GIF=1
      shift
      ;;
    --crf-mp4)
      CRF_MP4="$2"
      shift 2
      ;;
    --crf-webm)
      CRF_WEBM="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

require_ffmpeg

if [[ ! -d "${INPUT_DIR}" ]]; then
  echo "Input directory not found: ${INPUT_DIR}" >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"

GIFS=()
while IFS= read -r gif; do
  GIFS+=("${gif}")
done < <(find "${INPUT_DIR}" -maxdepth 1 -type f -name '*.gif' | sort)

if ((${#GIFS[@]} == 0)); then
  echo "No GIF files found in ${INPUT_DIR}" >&2
  exit 1
fi

total_before=0
total_after=0

for gif in "${GIFS[@]}"; do
  base="$(basename "${gif}" .gif)"
  mp4="${OUTPUT_DIR}/${base}.mp4"
  webm="${OUTPUT_DIR}/${base}.webm"
  optimized_gif="${OUTPUT_DIR}/${base}.gif"
  source_size="$(wc -c < "${gif}" | tr -d ' ')"

  log "${base}.gif ($(human_size "${source_size}"))"
  total_before=$((total_before + source_size))

  if (( DRY_RUN )); then
    echo "  would write ${mp4}"
    echo "  would write ${webm}"
    if (( ENCODE_GIF )); then
      echo "  would write ${optimized_gif}"
    fi
    continue
  fi

  encode_mp4 "${gif}" "${mp4}"
  encode_webm "${gif}" "${webm}"

  mp4_size="$(wc -c < "${mp4}" | tr -d ' ')"
  webm_size="$(wc -c < "${webm}" | tr -d ' ')"
  best_video_size="$webm_size"
  if (( mp4_size < best_video_size )); then
    best_video_size="$mp4_size"
  fi
  total_after=$((total_after + best_video_size))

  printf '  mp4  %s -> %s\n' "$(human_size "${source_size}")" "$(human_size "${mp4_size}")"
  printf '  webm %s -> %s\n' "$(human_size "${source_size}")" "$(human_size "${webm_size}")"

  if (( ENCODE_GIF )); then
    encode_optimized_gif "${gif}" "${optimized_gif}"
    optimized_size="$(wc -c < "${optimized_gif}" | tr -d ' ')"

    if (( optimized_size < source_size )); then
      printf '  gif  %s -> %s (smaller)\n' "$(human_size "${source_size}")" "$(human_size "${optimized_size}")"
      if (( REPLACE_GIF )); then
        cp -p "${gif}" "${gif}.bak"
        mv "${optimized_gif}" "${gif}"
        log "replaced ${gif} (backup at ${gif}.bak)"
      fi
    else
      printf '  gif  kept original (%s >= %s)\n' "$(human_size "${optimized_size}")" "$(human_size "${source_size}")"
      rm -f "${optimized_gif}"
    fi
  fi
done

if (( DRY_RUN )); then
  exit 0
fi

log "Done. Outputs in ${OUTPUT_DIR}"
if (( total_before > 0 )); then
  printf 'Best-case video savings vs GIF sources: %s -> %s (~%s%% smaller)\n' \
    "$(human_size "${total_before}")" \
    "$(human_size "${total_after}")" \
    "$(awk "BEGIN { printf \"%.0f\", (1 - ${total_after} / ${total_before}) * 100 }")"
fi
