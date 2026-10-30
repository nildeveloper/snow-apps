# macOS 13 compatibility CI

Pushes to `feature/macos13-compat` run the preflight workflow: native jthread
probes for both architectures, compatibility-policy checks and focused build
script/cache transport regression checks. These checks do not build the whole
application or publish packages.

The release workflow runs for `macos13-v<source-version>-r<revision>` tags. Its
manual dispatch can build `feature/macos13-compat` without publishing a release.
Tag builds still compile and package Full for ARM64 and Intel, plus ARM64 Mini,
with the release presets and their existing optimization/signing/checksum checks.
They do not use the fast presets or change release optimization levels.

## Compilation cache

The release job restores a repository artifact by name, independently of the
current branch/tag. The identity includes architecture, release preset, Apple
compiler/Xcode/SDK, stable Rust version, the pinned OCR nightly, Metal compiler,
CMake/ccache versions, Cargo manifests/locks and relevant native dependency
configuration. Incompatible configurations start cold.

The archive contains only Cargo registry/git dependency sources, the external
Cargo target directory and ccache objects. Cargo configuration and credentials
are excluded. Dependency sources travel with the compiled outputs to preserve
their timestamps. CMake configuration and application bundles are never restored.

`build.sh --clean` still creates a fresh CMake tree. The main Cargo target root
is passed explicitly outside that tree. C/C++/Objective-C++ use ccache, configured
with content-based compiler checks and the documented Clang PCH settings
(`pch_defines,time_macros`, `-Xclang -fno-pch-timestamp`). Build-time date macros
must not be used as release identity; the source version remains authoritative.
The existing Mini-specific helper target root remains build-local.

Packaging consumes the already built binaries with `--skip-build`, avoiding a
second build/cleanup. Compilation caches are saved even if compilation or
packaging fails, provided the job was not cancelled. Cargo rechecks fingerprints
and ccache checks inputs on the next build; partially completed builds are useful
without being treated as a successful release. Archives use zstd and are retained
for seven days; ccache has a 2 GiB limit per architecture. Artifact storage and
transfer costs should be monitored alongside hit rates.

## Validation and measurement

Run these focused checks from the repository root:

```sh
python3 scripts/test-macos13-compile-cache.py -v
python3 scripts/test-macos-build-support.py QtMacOSDeploymentPolicy \
  MacOSBuildScripts.test_ci_cached_build_cleans_cmake_without_rebuilding_for_packaging -v
```

Cache transport uses real tar/zstd with a simulated GitHub API. The build script
fixture validates command flow without compiling native macOS code. Native
release builds still require macOS runners. The first optimized build warms the
new cache; compare a subsequent compatible build's cache statistics and Actions
step durations before claiming an improvement. Rust changes, build-script native
inputs and final LTO links may still require substantial work on a cache hit.
