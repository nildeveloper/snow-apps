# macOS 13 OCR build compatibility

The compatibility release workflow explicitly runs
`python3 scripts/prepare-macos13-metal.py` before building Apple Silicon OCR.
For a local ARM64 application/OCR build, run the same preparation command before
using the unchanged upstream `scripts/build.sh`, CMake or Cargo entry point.
Intel and unrelated library/formatting targets do not need this preparation.
The shared build script deliberately contains no compatibility target dispatcher.

The helper verifies the OCR checkout matches the recorded submodule commit and
checks `macos13-metal-tt.patch` against a temporary copy of that committed source.
It accepts only the exact original `build.rs` or its exact patched form, refusing
unrelated local edits or a different submodule revision. After a successful native
toolchain probe it changes only `src/runtime/gpu/metal/build.rs` in the submodule
working tree and prints that action; the recorded commit and index are unchanged.
Repeated runs recognize the exact patch without rewriting it, but still probe the
current toolchain. A failed probe leaves the source untouched. This deliberately
retains the existing CI working-tree patch model rather than introducing another
Cargo workspace or silently rewriting user edits.

The Xcode 16 Metal translator on the macOS 15 runner rejects `-no-pack-sources`
and `-compress-resources`. These optional packing flags are removed from the
native pipeline archive command. Shader compilation, native archive generation,
GPU inference and the build script's final deflate compression remain enabled.

The same translator rejects the newer JSON descriptor fields `contention_relief`,
`forward_progress_usage` and `optimize_for_persistent_kernel`. The compatibility
patch omits these optional settings and uses the older descriptor defaults. It
retains function identity, threadgroup constraints, stack depth and binary-function
settings so the archive still matches the runtime pipeline descriptor.

Before applying the patch, the shared helper runs
`python3 scripts/check-macos13-metal-toolchain.py`. This compiles a tiny shader,
links its IR library and translates a native archive for the same SDK/architecture
and descriptor schema as OCR, before the expensive dependency and application
build. It fails on compiler/translator errors or an empty output. It does not
run a GPU kernel or validate OCR results.

This does not change the minimum application deployment target. The upstream
Metal backend requires macOS 14 or newer at runtime; macOS 13 retains CPU OCR.
The native application and shader build must still be validated on macOS.

Run `python3 scripts/test-prepare-macos13-metal.py -v` for focused temporary-Git
fixtures covering repeat application, revision mismatch, user changes, symlinks,
patch mismatch and probe failure. These require the initialized OCR submodule but
do not modify it or require a native Metal toolchain.

Run `python3 scripts/test-macos13-metal-build.py -v` with Cargo on `PATH` for the
focused build-script regression check. It reproduces the rejected argument with
a simulated old translator, reproduces r2's unknown JSON field failure, applies
the patch to a temporary source copy, checks
archive compression and cache reuse, and verifies that shader errors still fail
the build. It does not compile or validate native Metal shaders.
