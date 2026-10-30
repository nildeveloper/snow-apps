"""Focused cache transport and release artifact isolation regression tests."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/macos13-compile-cache.sh'
GH = '''#!/usr/bin/env python3
import json, os, pathlib, sys
with open(os.environ['CACHE_TEST_LOG'], 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
if os.environ.get('CACHE_TEST_DENIED'):
    sys.exit('API permission denied')
if sys.argv[2].endswith('/zip'):
    sys.stdout.buffer.write(pathlib.Path(os.environ['CACHE_TEST_ZIP']).read_bytes())
elif os.environ.get('CACHE_TEST_ZIP'):
    print('73')
'''


class CompilationCache(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='snow compile cache ')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.cache = self.directory / 'compilation'
        self.tools = self.directory / 'bin'
        self.tools.mkdir()
        (self.tools / 'gh').write_text(GH)
        (self.tools / 'gh').chmod(0o755)
        self.artifact = 'macos13-compile-arm64-test-fingerprint'
        self.environment = dict(os.environ,
            SNOW_COMPILE_CACHE_ROOT=str(self.cache), COMPILE_CACHE_ARTIFACT=self.artifact,
            RUNNER_TEMP=str(self.directory), GITHUB_REPOSITORY='fixture/snow-apps',
            PATH=str(self.tools) + os.pathsep + os.environ['PATH'],
            CACHE_TEST_LOG=str(self.directory / 'calls.jsonl'))

    def run_cache(self, mode):
        return subprocess.run(['bash', str(SCRIPT), mode], env=self.environment,
                              text=True, capture_output=True)

    def test_cold_cache_allows_building(self):
        result = self.run_cache('restore')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('cold build', result.stdout)
        self.assertTrue((self.cache / 'cargo-target').is_dir())
        calls = (self.directory / 'calls.jsonl').read_text().splitlines()
        self.assertEqual(len(calls), 1, 'a cold cache must not download an archive')

    def test_round_trip_preserves_compiler_outputs_and_excludes_credentials(self):
        self.run_cache('restore')
        files = {'cargo-target/release/deps/library.rlib': b'compiled dependency',
                 'ccache/a/b/object': b'compiled C++',
                 'cargo-home/registry/src/example/lib.rs': b'source code',
                 'cargo-home/git/checkouts/dependency/source.rs': b'git source'}
        for relative, contents in files.items():
            path = self.cache / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
            os.utime(path, (1700000000, 1700000000))
        (self.cache / 'cargo-home/credentials.toml').write_text('must not be cached')
        (self.cache / 'cargo-home/config.toml').write_text('must not be cached')
        result = self.run_cache('pack')
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = self.directory / (self.artifact + '.tar.zst')
        zipped = self.directory / 'artifact.zip'
        with zipfile.ZipFile(zipped, 'w') as package:
            package.write(archive, archive.name)
        shutil.rmtree(self.cache)
        self.environment['CACHE_TEST_ZIP'] = str(zipped)
        result = self.run_cache('restore')
        self.assertEqual(result.returncode, 0, result.stderr)
        for relative, contents in files.items():
            self.assertEqual((self.cache / relative).read_bytes(), contents)
            self.assertEqual(int((self.cache / relative).stat().st_mtime), 1700000000)
        self.assertFalse((self.cache / 'cargo-home/credentials.toml').exists())
        self.assertFalse((self.cache / 'cargo-home/config.toml').exists())
        calls = [json.loads(line) for line in
                 (self.directory / 'calls.jsonl').read_text().splitlines()]
        self.assertIn('name=' + self.artifact, calls[-2][1])

    def test_permission_failure_is_not_misreported_as_cold_cache(self):
        self.environment['CACHE_TEST_DENIED'] = '1'
        result = self.run_cache('restore')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('API permission denied', result.stderr)
        self.assertNotIn('cold build', result.stdout)

    def test_corrupt_archive_fails_restoration(self):
        zipped = self.directory / 'artifact.zip'
        with zipfile.ZipFile(zipped, 'w') as package:
            package.writestr(self.artifact + '.tar.zst', b'not a zstd stream')
        self.environment['CACHE_TEST_ZIP'] = str(zipped)
        result = self.run_cache('restore')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Restored compilation cache', result.stdout)


class ReleaseValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = (ROOT / '.github/workflows/macos13-compat-release.yml').read_text()
        validation = workflow.split('\n  build:\n', 1)[0]
        cls.command = textwrap.dedent(validation.split('        run: |\n', 1)[1])
        cls.release = workflow.split('\n  release:\n', 1)[1]

    def validate(self, ref_type, ref_name, source_version='1.4.3', target='13.0'):
        with tempfile.TemporaryDirectory(prefix='snow release validation ') as temporary:
            directory = Path(temporary)
            (directory / 'scripts').mkdir()
            (directory / 'CMakeLists.txt').write_text(
                f'set(SNOW_SHOT_VERSION "{source_version}")\n'
                f'set(CMAKE_OSX_DEPLOYMENT_TARGET "{target}" CACHE STRING "")\n')
            (directory / 'scripts/qt-toolchain.json').write_text(
                json.dumps({'macosQtDeploymentTarget': target}))
            output = directory / 'output'
            environment = dict(os.environ, GITHUB_REF_TYPE=ref_type,
                               GITHUB_REF_NAME=ref_name, GITHUB_OUTPUT=str(output))
            result = subprocess.run(['bash', '-c', self.command], cwd=directory,
                                    env=environment, text=True, capture_output=True)
            values = dict(line.split('=', 1) for line in output.read_text().splitlines()) \
                if output.exists() else {}
            return result, values

    def test_supported_branches_build_without_publishing(self):
        for branch in ('feature/macos13-compat', 'fix/macos13-v1.4.3-pin-constructor'):
            with self.subTest(branch=branch):
                result, values = self.validate('branch', branch)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(values, {'version': '1.4.3', 'revision': 'smoke',
                                         'release_tag': '', 'publish': 'false'})
        self.assertIn("if: needs.validate.outputs.publish == 'true'", self.release)

    def test_unrelated_branches_are_rejected(self):
        for branch in ('main', 'fix/macos14-probe', 'feature/macos13-compat-other'):
            with self.subTest(branch=branch):
                result, values = self.validate('branch', branch)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Unsupported smoke-build branch', result.stderr)
                self.assertEqual(values, {})

    def test_valid_tag_preserves_publishing(self):
        result, values = self.validate('tag', 'macos13-v1.4.3-r4')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values, {'version': '1.4.3', 'revision': '4',
                                 'release_tag': 'macos13-v1.4.3-r4', 'publish': 'true'})

    def test_invalid_or_mismatched_tags_are_rejected(self):
        for tag in ('macos13-v1.4.3-r0', 'v1.4.3_snow-shot',
                    'macos13-v1.4.2-r4', 'fix/macos13-v1.4.3-pin-constructor'):
            with self.subTest(tag=tag):
                result, values = self.validate('tag', tag)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(values, {})

    def test_smoke_build_still_requires_compatible_deployment_target(self):
        result, values = self.validate('branch', 'fix/macos13-probe', target='15.0')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(values, {})


class ReleaseArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = ROOT / '.github/workflows/macos13-compat-release.yml'
        cls.release = workflow.read_text().split('\n  release:\n', 1)[1]

    def test_downloads_only_packaged_architecture_artifacts(self):
        downloads = re.findall(
            r'uses: actions/download-artifact@[^\n]+\n\s+with:\n\s+name:\s*(\S+)',
            self.release)
        self.assertCountEqual(downloads, ['macos13-arm64', 'macos13-x64'])
        self.assertEqual(self.release.count('uses: actions/download-artifact@'), 2)
        self.assertNotRegex(self.release, r'(?m)^\s+pattern:')

    def test_publish_commands_exclude_cache_archives(self):
        commands = [line.strip() for line in self.release.splitlines()
                    if re.match(r'\s*gh release (?:create|upload)\s', line)]
        self.assertEqual(len(commands), 2, 'check both initial publication and retry')
        with tempfile.TemporaryDirectory(prefix='snow release assets ') as temporary:
            directory = Path(temporary)
            dist = directory / 'dist'
            tools = directory / 'bin'
            dist.mkdir()
            tools.mkdir()
            packages = ['snow-shot-1.4.3-macos-arm64.dmg',
                        'snow-shot-mini-1.4.3-macos-arm64.dmg',
                        'snow-shot-1.4.3-macos-x86_64.dmg']
            assets = packages + [name + '.sha256' for name in packages]
            caches = ['macos13-vcpkg-arm64-cache.tar.gz',
                      'macos13-static-qt-x64-cache.tar.gz',
                      'macos13-compile-arm64-cache.tar.zst', 'unrelated.txt']
            for name in assets + caches:
                (dist / name).write_text('fixture')
            gh = tools / 'gh'
            gh.write_text('#!/usr/bin/env python3\n'
                          'import json, sys\nprint(json.dumps(sys.argv[1:]))\n')
            gh.chmod(0o755)
            environment = dict(os.environ,
                PATH=str(tools) + os.pathsep + os.environ['PATH'],
                RELEASE_TAG='macos13-v1.4.3-r4', GITHUB_REPOSITORY='fixture/snow-apps',
                title='fixture release')
            for command in commands:
                with self.subTest(command=command.split()[2]):
                    result = subprocess.run(['bash', '-euo', 'pipefail', '-c', command],
                                            cwd=directory, env=environment,
                                            text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    arguments = json.loads(result.stdout)
                    uploads = [value for value in arguments if value.startswith('dist/')]
                    self.assertCountEqual(uploads, ['dist/' + name for name in assets])


if __name__ == '__main__':
    unittest.main()
