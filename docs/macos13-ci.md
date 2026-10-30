# macOS 13 compatibility CI

Pushes to `feature/macos13-compat` and `fix/macos13-*` run the preflight workflow:
native jthread probes for both architectures, compatibility-policy checks and focused build
script/cache transport regression checks. Native probes also exercise stop-aware
waiting with the selected standard library/backport and a forced fallback.
These checks do not build the whole application or publish packages.

The release workflow runs for `macos13-v<source-version>-r<revision>` tags. Manual
dispatch is also restricted to compatibility tags; branch dispatch is rejected
before any native build. There is no extra full smoke build before a tag release.
Tag builds still compile and package Full for ARM64 and Intel, plus ARM64 Mini,
with the release presets and their existing optimization/signing/checksum checks.
They do not use the fast presets or change release optimization levels.
Both architectures run focused `snow-macos` capability and lazy display-fallback
tests, plus the 1.4.4 C live-window profile test, before building the application;
these do not test physical capture behavior.

## Compilation cache

The release job restores a repository artifact by name, independently of the
current branch/tag. The identity includes architecture, release preset, Apple
compiler/Xcode/SDK, stable Rust version, the pinned OCR nightly, Metal compiler,
CMake/ccache versions and relevant native dependency ABI configuration.
Cargo manifests/locks, application sources/CMake lists and documentation no longer
discard the entire cache: Cargo and ccache validate their own inputs. Qt policy and
builder scripts, vcpkg manifests/overlays, OCR patches and Rust native integration
still invalidate the cache to avoid reusing crates against changed native libraries.
Incompatible configurations start cold. The v2 identity is a one-time cold compiler
cache migration; separately validated Qt/vcpkg artifacts remain reusable.

The archive contains only Cargo registry/git dependency sources, the external
Cargo target directory and ccache objects. Cargo configuration and credentials
are excluded. Dependency sources travel with the compiled outputs to preserve
their timestamps. CMake configuration and application bundles are never restored.

`build.sh --clean` still creates a fresh CMake tree. The main Cargo target root
is passed explicitly outside that tree. C/C++/Objective-C++ use ccache, configured
with content-based compiler checks and the documented Clang PCH settings
(`pch_defines,time_macros`, `-Xclang -fno-pch-timestamp`). Build-time date macros
must not be used as release identity; the source version remains authoritative.
Full, Mini helpers and native tests use separate persistent roots under
`cargo-target/{full,mini,tests}`. Mini defaults to its original build-local directory
outside CI, and rejects a target directory shared with Full. Generated compatibility
headers retain their timestamp on no-op configure; app diagnostics revision macros
apply only to `main.cpp`, not unrelated application translation units.

Packaging consumes the already built binaries with `--skip-build`, avoiding a
second build/cleanup. Compilation caches are saved even if compilation or
packaging fails, provided the job was not cancelled. Cargo rechecks fingerprints
and ccache checks inputs on the next build; partially completed builds are useful
without being treated as a successful release. Archives use zstd and are retained
for fourteen days; ccache has a 2 GiB limit per architecture. Artifact storage and
transfer costs should be monitored alongside hit rates.

## Validation and measurement

Run these focused checks from the repository root:

```sh
python3 scripts/test-macos13-compile-cache.py -v
python3 scripts/test-prepare-macos13-metal.py -v
python3 scripts/test-diagnostics-compile-scope.py -v
python3 scripts/test-macos-build-support.py QtMacOSDeploymentPolicy MiniCargoCachePolicy \
  MacOSBuildScripts.test_ci_cached_build_cleans_cmake_without_rebuilding_for_packaging -v
```

Cache transport uses real tar/zstd with a simulated GitHub API. The build script
fixture validates command flow without compiling native macOS code. Native
release builds still require macOS runners. The first optimized build warms the
new cache; compare a subsequent compatible build's cache statistics and Actions
step durations before claiming an improvement. Rust changes, build-script native
inputs and final LTO links may still require substantial work on a cache hit.
