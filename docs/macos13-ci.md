# macOS 13 compatibility CI

## Persistent release signatures

Compatibility tag builds require these GitHub **Actions Secrets** (not plaintext
Actions Variables), using the same names and rcodesign flow as
[paste-rs](https://github.com/nildeveloper/paste-rs/blob/2b3c7387264f55a25aa5bc634b869777f670e178/.github/workflows/build.yml):

- `MACOS_SIGNING_P12_BASE64`: a single-line base64-encoded PKCS#12 certificate and private key.
- `MACOS_SIGNING_P12_PASSWORD`: that container's password.

The same certificate may be used for both projects. Repository secrets must be
configured in this repository too, or provided through an organization secret
authorized for both repositories. The workflow cannot copy another repository's
secret values. Keep the certificate/key fixed across releases; certificate
rotation changes the application's identity for existing privacy grants.

Before the expensive build, the workflow validates the P12 and certificate
expiration, downloads checksum-pinned rcodesign 0.29.0, and signs tiny native Full
and Mini bundles. Apple codesign verifies the architecture-specific probes,
certificate requirement and preserved nested helper bytes. Missing credentials
or probe failures stop the release without falling back to ad-hoc signing.
The probe uses the production `prepare-bundle` resource-staging path, including
the `MacOS/assets` link to `Resources/assets`; JSON files are not placed in the
nested-code area. Apple verification errors include verbose resource diagnostics.

CPack's final app-staging hook signs the actual deployment copy after stripping,
OCR finalization and product-name staging. `--exclude '**'` preserves the nested
helpers and finalized OCR manifest. Before creating the DMG, signing verifies
unchanged nested resources, the deep bundle signature, expected Bundle ID and
certificate fingerprint, and a designated requirement without `cdhash`.
Only the DMG container is signed after this point. The certificate/password live
under the runner's temporary directory with restricted permissions, are excluded
from all caches/artifacts, and are removed by an `always()` cleanup step.

These are certificate-signed apps, not Apple-notarized releases. Switching from
the old ad-hoc builds can require one new Screen Recording/Accessibility grant.
Install a later, different build by DMG drag-and-drop using the same certificate
and verify both capabilities on macOS 13 before claiming permission retention.
Do not use the local-signing installer when testing this distribution identity;
that installer intentionally signs with its own local certificate.

Run `python3 scripts/test-sign-macos13-release.py -v` with OpenSSL and CMake for
focused orchestration tests. Linux tests use real temporary P12 containers and
simulated Apple signing commands. They do not prove native signature validity
or TCC permission continuity; the native probe and Mac upgrade check do that.

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

CI requires a fresh CMake tree and invokes the unchanged upstream `build.sh`.
Only Cargo outputs and ccache are restored, never CMake configuration, native
object trees or application bundles. Full and native tests have explicit separate
external target roots. For ARM64, CI links upstream's fixed `build/<preset>/cargo-mini`
path to the separate `cargo-target/mini` cache; no Mini CMake policy fork is needed.
C/C++/Objective-C++ use ccache with content-based compiler checks and the documented
Clang PCH settings (`pch_defines,time_macros`, `-Xclang -fno-pch-timestamp`).
The upstream diagnostics revision macros are unchanged; a new revision can still
invalidate affected application translation units even with a cache hit.
The compatibility-only generated header retains its timestamp on no-op configure.

Dependency tree and compiler archives share one transport helper. Qt and vcpkg
still retain their distinct exact identities and post-restore validation. A cache
miss is allowed; permission failures or corrupt archives fail rather than being
silently reported as a miss. Metal preparation is an explicit compatibility step,
not a change to the shared build or packaging entry points.

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
python3 scripts/test-macos-build-support.py QtMacOSDeploymentPolicy \
  MacOSBuildScripts.test_ci_cached_build_reuses_only_compiler_outputs_and_packages_once -v
```

Cache transport uses real tar/zstd with a simulated GitHub API. The build script
fixture validates command flow without compiling native macOS code. Native
release builds still require macOS runners. The first optimized build warms the
new cache; compare a subsequent compatible build's cache statistics and Actions
step durations before claiming an improvement. Rust changes, build-script native
inputs and final LTO links may still require substantial work on a cache hit.
