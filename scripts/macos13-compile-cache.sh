#!/bin/bash
# Shared artifact transport for dependency trees and isolated compilation outputs.
set -euo pipefail
mode="${1:?Usage: macos13-compile-cache.sh restore|pack|restore-tree|pack-tree}"
case "$mode" in
    restore|pack)
        root="${SNOW_COMPILE_CACHE_ROOT:?}"
        artifact="${COMPILE_CACHE_ARTIFACT:?}"
        extension=tar.zst
        mkdir -p "$root/cargo-target" "$root/ccache" \
            "$root/cargo-home/registry" "$root/cargo-home/git"
        ;;
    restore-tree|pack-tree)
        artifact="${2:?Artifact name required}"
        root="${3:?Tree prefix required}"
        extension=tar.gz
        ;;
    *) echo "Unknown compilation cache command: $mode" >&2; exit 2 ;;
esac

case "$mode" in
    restore|restore-tree)
        artifact_id="$(gh api "/repos/${GITHUB_REPOSITORY:?}/actions/artifacts?name=$artifact&per_page=100" \
            -H 'X-GitHub-Api-Version: 2022-11-28' \
            --jq '[.artifacts[] | select(.expired == false)] | sort_by(.created_at) | last | .id // empty')"
        if [[ -z "$artifact_id" ]]; then
            if [[ "$mode" == restore-tree ]]; then
                echo false
            else
                echo 'No compatible compilation cache found; starting a cold build.'
            fi
            exit 0
        fi
        temporary="$(mktemp -d "${RUNNER_TEMP:?}/snow-compile-cache.XXXXXX")"
        trap 'rm -rf -- "$temporary"' EXIT
        gh api "/repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id/zip" \
            -H 'X-GitHub-Api-Version: 2022-11-28' > "$temporary/artifact.zip"
        unzip -q "$temporary/artifact.zip" -d "$temporary"
        if [[ "$mode" == restore-tree ]]; then
            rm -rf -- "$root"
            mkdir -p "$(dirname "$root")"
            tar -xzf "$temporary/$artifact.$extension" -C "$(dirname "$root")"
            # A transport hit still requires the caller's dependency validation.
            echo true
        else
            zstd -dc "$temporary/$artifact.$extension" | tar -xf - -C "$root"
            printf 'Restored compilation cache %s (artifact %s).\n' "$artifact" "$artifact_id"
        fi
        ;;
    pack|pack-tree)
        archive="${RUNNER_TEMP:?}/$artifact.$extension"
        if [[ "$mode" == pack-tree ]]; then
            tar -czf "$archive" -C "$(dirname "$root")" "$(basename "$root")"
        else
            # Cache only registry/git sources and build outputs, never Cargo config,
            # credentials, rustup installations or a generated CMake build tree.
            tar -cf - -C "$root" cargo-target ccache cargo-home/registry cargo-home/git |
                zstd -T2 -3 -f -o "$archive"
        fi
        ls -lh "$archive"
        ;;
esac
