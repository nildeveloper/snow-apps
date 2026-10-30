"""Focused cache transport tests using real tar/zstd and a simulated GitHub API."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
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


if __name__ == '__main__':
    unittest.main()
