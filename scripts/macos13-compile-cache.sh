#!/bin/bash
# Keep compilation outputs separate from the disposable CMake build tree.
set -euo pipefail
mode="${1:?Usage: macos13-compile-cache.sh restore|pack}"
root="${SNOW_COMPILE_CACHE_ROOT:?}"
artifact="${COMPILE_CACHE_ARTIFACT:?}"
mkdir -p "$root/cargo-target" "$root/ccache" \
    "$root/cargo-home/registry" "$root/cargo-home/git"

case "$mode" in
    restore)
        artifact_id="$(gh api "/repos/${GITHUB_REPOSITORY:?}/actions/artifacts?name=$artifact&per_page=100" \
            --jq '[.artifacts[] | select(.expired == false)] | sort_by(.created_at) | last | .id // empty')"
        if [[ -z "$artifact_id" ]]; then
            echo 'No compatible compilation cache found; starting a cold build.'
            exit 0
        fi
        temporary="$(mktemp -d "${RUNNER_TEMP:?}/snow-compile-cache.XXXXXX")"
        trap 'rm -rf -- "$temporary"' EXIT
        gh api "/repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id/zip" > "$temporary/artifact.zip"
        unzip -q "$temporary/artifact.zip" -d "$temporary"
        zstd -dc "$temporary/$artifact.tar.zst" | tar -xf - -C "$root"
        printf 'Restored compilation cache %s (artifact %s).\n' "$artifact" "$artifact_id"
        ;;
    pack)
        archive="${RUNNER_TEMP:?}/$artifact.tar.zst"
        # Cache only registry/git sources and build outputs, never Cargo config,
        # credentials, rustup installations or a generated CMake build tree.
        tar -cf - -C "$root" cargo-target ccache cargo-home/registry cargo-home/git |
            zstd -T2 -3 -f -o "$archive"
        ls -lh "$archive"
        ;;
    *) echo "Unknown compilation cache command: $mode" >&2; exit 2 ;;
esac
