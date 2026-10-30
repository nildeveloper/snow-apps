# macOS 13 OCR build compatibility

The compatibility release workflow applies `macos13-metal-tt.patch` to its
checked-out OCR submodule before building the ARM64 worker. The patch is checked
with `git apply --check`, so a changed upstream source fails before compilation.
The recorded submodule commit is unchanged.

The Xcode 16 Metal translator on the macOS 15 runner rejects `-no-pack-sources`
and `-compress-resources`. These optional packing flags are removed from the
native pipeline archive command. Shader compilation, native archive generation,
GPU inference and the build script's final deflate compression remain enabled.

The same translator rejects the newer JSON descriptor fields `contention_relief`,
`forward_progress_usage` and `optimize_for_persistent_kernel`. The compatibility
patch omits these optional settings and uses the older descriptor defaults. It
retains function identity, threadgroup constraints, stack depth and binary-function
settings so the archive still matches the runtime pipeline descriptor.

After applying the patch, the workflow runs
`python3 scripts/check-macos13-metal-toolchain.py`. This compiles a tiny shader,
links its IR library and translates a native archive for the same SDK/architecture
and descriptor schema as OCR, before the expensive dependency and application
build. It fails on compiler/translator errors or an empty output. It does not
run a GPU kernel or validate OCR results.

This does not change the minimum application deployment target. The upstream
Metal backend requires macOS 14 or newer at runtime; macOS 13 retains CPU OCR.
The native application and shader build must still be validated on macOS.

Run `python3 scripts/test-macos13-metal-build.py -v` with Cargo on `PATH` for the
focused build-script regression check. It reproduces the rejected argument with
a simulated old translator, reproduces r2's unknown JSON field failure, applies
the patch to a temporary source copy, checks
archive compression and cache reuse, and verifies that shader errors still fail
the build. It does not compile or validate native Metal shaders.
