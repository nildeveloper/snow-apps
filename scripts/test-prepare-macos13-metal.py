"""Focused source preparation tests; uses temporary Git repos, no Metal SDK."""

import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_metal', ROOT / 'scripts/prepare-macos13-metal.py')
prepare_metal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_metal)


class MetalPreparation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='snow metal git fixture ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ocr = self.root / prepare_metal.SUBMODULE
        self.source = self.ocr / prepare_metal.SOURCE
        self.source.parent.mkdir(parents=True)
        self.original = prepare_metal.git(ROOT / prepare_metal.SUBMODULE,
                                          'show', 'HEAD:' + prepare_metal.SOURCE)
        self.source.write_bytes(self.original)
        for repository in (self.root, self.ocr):
            self.git(repository, 'init', '-q')
            self.git(repository, 'config', 'user.email', 'fixture@example.invalid')
            self.git(repository, 'config', 'user.name', 'Test Fixture')
        self.git(self.ocr, 'add', prepare_metal.SOURCE)
        self.git(self.ocr, 'commit', '-qm', 'pinned OCR source')
        sha = self.git(self.ocr, 'rev-parse', 'HEAD').decode().strip()
        self.git(self.root, 'update-index', '--add', '--cacheinfo',
                 '160000,' + sha + ',' + prepare_metal.SUBMODULE)
        self.git(self.root, 'commit', '-qm', 'pin OCR')
        patch = self.root / 'cmake/ocr/macos13-metal-tt.patch'
        patch.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / 'cmake/ocr/macos13-metal-tt.patch', patch)
        self.probes = 0

    def git(self, directory, *args):
        return prepare_metal.git(directory, *args)

    def probe(self, root):
        self.assertEqual(root, self.root)
        self.probes += 1

    def prepare(self):
        return prepare_metal.prepare(self.root, self.probe)

    def test_first_application_and_repeat_are_exact_and_idempotent(self):
        pin = self.git(self.ocr, 'rev-parse', 'HEAD')
        self.assertTrue(self.prepare())
        patched = self.source.read_bytes()
        self.assertNotEqual(patched, self.original)
        mtime = self.source.stat().st_mtime_ns
        self.assertFalse(self.prepare())
        self.assertEqual(self.source.read_bytes(), patched)
        self.assertEqual(self.source.stat().st_mtime_ns, mtime)
        self.assertEqual(self.git(self.ocr, 'rev-parse', 'HEAD'), pin)
        self.assertEqual(self.probes, 2)

    def test_local_changes_are_not_overwritten(self):
        changed = self.original + b'\n// local customization\n'
        self.source.write_bytes(changed)
        with self.assertRaisesRegex(RuntimeError, 'local changes'):
            self.prepare()
        self.assertEqual(self.source.read_bytes(), changed)
        self.assertEqual(self.probes, 0)

    def test_wrong_submodule_revision_is_rejected(self):
        self.git(self.ocr, 'commit', '--allow-empty', '-qm', 'unexpected revision')
        with self.assertRaisesRegex(RuntimeError, 'recorded submodule commit'):
            self.prepare()
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.probes, 0)

    def test_local_changes_after_patch_are_not_overwritten(self):
        self.prepare()
        changed = self.source.read_bytes() + b'\n// local customization\n'
        self.source.write_bytes(changed)
        with self.assertRaisesRegex(RuntimeError, 'local changes'):
            self.prepare()
        self.assertEqual(self.source.read_bytes(), changed)
        self.assertEqual(self.probes, 1)

    def test_symlinked_source_is_rejected(self):
        external = self.root / 'external.rs'
        external.write_bytes(self.original)
        self.source.unlink()
        self.source.symlink_to(external)
        with self.assertRaisesRegex(RuntimeError, 'symlinked'):
            self.prepare()
        self.assertEqual(external.read_bytes(), self.original)
        self.assertEqual(self.probes, 0)

    def test_probe_failure_leaves_source_untouched(self):
        def fail(_):
            raise RuntimeError('fixture toolchain failure')
        with self.assertRaisesRegex(RuntimeError, 'fixture toolchain failure'):
            prepare_metal.prepare(self.root, fail)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_changed_source_during_probe_is_not_overwritten(self):
        changed = self.original + b'\n// concurrent edit\n'
        def edit(_):
            self.source.write_bytes(changed)
        with self.assertRaisesRegex(RuntimeError, 'changed during'):
            prepare_metal.prepare(self.root, edit)
        self.assertEqual(self.source.read_bytes(), changed)

    def test_incompatible_patch_fails_before_touching_source(self):
        patch = self.root / 'cmake/ocr/macos13-metal-tt.patch'
        patch.write_text(patch.read_text().replace('support_adding_binary_functions',
                                                  'not_present_in_pinned_source'))
        with self.assertRaises(subprocess.CalledProcessError):
            self.prepare()
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.probes, 0)


if __name__ == '__main__':
    unittest.main()
