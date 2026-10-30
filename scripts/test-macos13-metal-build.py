"""Exercise the real OCR build script against a simulated Xcode 16 translator.

Requires Cargo and network access to its public registry on a cold cache.
This checks command compatibility and failure propagation, not native shaders.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib


ROOT = Path(__file__).resolve().parents[1]
OCR = ROOT / 'snow-crates/crates/simd-paddle-ocr-rs'
PATCH = ROOT / 'cmake/ocr/macos13-metal-tt.patch'

XCRUN = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
assert args[:2] == ['--sdk', 'macosx'], args
args = args[2:]
if args == ['--show-sdk-version']:
    print('15.5')
    sys.exit(0)
if args == ['metal', '--version']:
    print('Apple metal version 32023.98 (fixture)')
    sys.exit(0)
with open(os.environ['MOCK_METAL_LOG'], 'a') as stream:
    stream.write(json.dumps(args) + '\n')
if os.environ.get('MOCK_METAL_FAIL'):
    sys.exit('fixture: shader compilation failed')
if args[0] == 'metal-tt':
    for flag in ('-no-pack-sources', '-compress-resources'):
        if flag in args:
            sys.exit('metal-tt: unknown argument: ' + flag)
    assert args[args.index('-target') + 1] == 'air64-apple-macos15.0'
    assert args[args.index('-arch') + 1] == 'applegpu_g16g'
    spec = json.loads(Path(args[1]).read_text())
    assert spec['pipelines']['compute_pipelines']
    defaults = {
        'threadgroup_size_is_multiple_of_thread_execution_width': False,
        'max_total_threads_per_threadgroup': 0,
        'max_call_stack_depth': 1,
        'support_indirect_command_buffers': False,
        'support_adding_binary_functions': False,
    }
    for pipeline in spec['pipelines']['compute_pipelines']:
        unknown = set(pipeline) - set(defaults) - {'compute_function'}
        if unknown:
            sys.exit('metal-tt: unknown field: ' + sorted(unknown)[0])
        assert pipeline['compute_function'].startswith('alias:OCR#')
        assert {key: pipeline[key] for key in defaults} == defaults
assert args[0] in ('metal', 'metallib', 'metal-tt'), args
Path(args[args.index('-o') + 1]).write_bytes(b'fixture archive data')
'''


class MetalBuildCompatibility(unittest.TestCase):
    def test_old_translator_builds_archives_and_preserves_real_failures(self):
        with tempfile.TemporaryDirectory(prefix='snow-metal-compat-') as directory:
            root = Path(directory)
            metal = root / 'src/runtime/gpu/metal'
            shutil.copytree(OCR / 'src/runtime/gpu/metal', metal)
            (root / 'Cargo.toml').write_text('''[package]
name = "snow-metal-build-contract"
version = "0.0.0"
edition = "2024"
[dependencies]
serde_json = "=1.0.149"
miniz_oxide = "=0.8.9"
''')
            (root / 'src/main.rs').write_text(
                '#[path = "runtime/gpu/metal/build.rs"]\n'
                'mod metal_build;\nfn main() { metal_build::build(); }\n')
            tools = root / 'tools'
            tools.mkdir()
            (tools / 'xcrun').write_text(XCRUN)
            (tools / 'xcrun').chmod(0o755)
            out = root / 'out'
            out.mkdir()
            log = root / 'commands.jsonl'
            environment = dict(os.environ, OUT_DIR=str(out),
                               PATH=str(tools) + os.pathsep + os.environ['PATH'],
                               MOCK_METAL_LOG=str(log))
            environment.pop('SIMD_OCR_METAL_TOOLCHAIN', None)

            def cargo(*args):
                return subprocess.run(['cargo', *args], cwd=root, env=environment,
                                      text=True, capture_output=True)

            lock = cargo('generate-lockfile')
            self.assertEqual(lock.returncode, 0, lock.stderr)
            baseline = cargo('run', '--locked', '--quiet')
            self.assertNotEqual(baseline.returncode, 0)
            self.assertIn('unknown argument: -no-pack-sources', baseline.stderr)

            # Reproduce r2 as well: removing only the command-line flags still
            # fails because the old translator rejects newer JSON fields.
            build_script = metal / 'build.rs'
            original = build_script.read_text()
            build_script.write_text(original.replace(
                '                "-no-pack-sources",\n                "-compress-resources",\n', ''))
            flags_only = cargo('run', '--locked', '--quiet')
            self.assertNotEqual(flags_only.returncode, 0)
            self.assertIn('unknown field: contention_relief', flags_only.stderr)
            build_script.write_text(original)

            # Apply the same exact patch as CI, to an isolated copy of the
            # pinned sources. Never modify the actual submodule during testing.
            for extra in (['--check'], []):
                applied = subprocess.run(
                    ['git', 'apply', *extra, str(PATCH)], cwd=root,
                    text=True, capture_output=True)
                self.assertEqual(applied.returncode, 0, applied.stderr)
            patched = cargo('run', '--locked', '--quiet')
            self.assertEqual(patched.returncode, 0, patched.stderr)
            self.assertIn('SIMD_OCR_METAL_ARCHIVE_OS=15', patched.stdout)
            for name in ('ocr.metallib', 'ocr.binary.metallib'):
                self.assertEqual(zlib.decompress((out / (name + '.deflate')).read_bytes(), -15),
                                 (out / name).read_bytes())
            before = log.read_bytes()
            cached = cargo('run', '--locked', '--quiet')
            self.assertEqual(cached.returncode, 0, cached.stderr)
            self.assertEqual(log.read_bytes(), before, 'unchanged shaders must reuse outputs')

            def probe():
                return subprocess.run(
                    [sys.executable, str(ROOT / 'scripts/check-macos13-metal-toolchain.py')],
                    env=environment, text=True, capture_output=True)

            checked = probe()
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertIn('native archive probe passed', checked.stdout)
            (out / 'metal-compiler.txt').unlink()
            environment['MOCK_METAL_FAIL'] = '1'
            failed = cargo('run', '--locked', '--quiet')
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn('fixture: shader compilation failed', failed.stderr)
            rejected = probe()
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn('fixture: shader compilation failed', rejected.stderr)


if __name__ == '__main__':
    unittest.main()
