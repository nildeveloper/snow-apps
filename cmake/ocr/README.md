# macOS 13 OCR build compatibility

The compatibility release workflow applies `macos13-metal-tt.patch` to its
checked-out OCR submodule before building the ARM64 worker. The patch is checked
with `git apply --check`, so a changed upstream source fails before compilation.
The recorded submodule commit is unchanged.

The Xcode 16 Metal translator on the macOS 15 runner rejects `-no-pack-sources`
and `-compress-resources`. These optional packing flags are removed from the
native pipeline archive command. Shader compilation, native archive generation,
GPU inference and the build script's final deflate compression remain enabled.

This does not change the minimum application deployment target. The upstream
Metal backend requires macOS 14 or newer at runtime; macOS 13 retains CPU OCR.
The native application and shader build must still be validated on macOS.

Run `python3 scripts/test-macos13-metal-build.py -v` with Cargo on `PATH` for the
focused build-script regression check. It reproduces the rejected argument with
a simulated old translator, applies the patch to a temporary source copy, checks
archive compression and cache reuse, and verifies that shader errors still fail
the build. It does not compile or validate native Metal shaders.
