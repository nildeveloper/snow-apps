"""Focused signing orchestration tests; Apple signature/TCC checks still need macOS."""

import base64
import contextlib
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_signing', ROOT / 'scripts/sign-macos13-release.py')
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)


class ReleaseSigning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.material = tempfile.TemporaryDirectory(prefix='snow-signing-fixture-')
        cls.addClassCleanup(cls.material.cleanup)
        root = Path(cls.material.name)
        cls.password = 'test-only-password'
        (root / 'password').write_text(cls.password)
        for args in (
            ['req', '-new', '-newkey', 'rsa:2048', '-nodes', '-x509', '-days', '2',
             '-subj', '/CN=Signing Test Fixture', '-addext', 'extendedKeyUsage=codeSigning',
             '-keyout', str(root / 'key.pem'), '-out', str(root / 'cert.pem')],
            ['pkcs12', '-export', '-inkey', str(root / 'key.pem'), '-in', str(root / 'cert.pem'),
             '-out', str(root / 'fixture.p12'), '-passout', 'file:' + str(root / 'password')],
        ):
            subprocess.run(['openssl', *args], check=True, capture_output=True)
        cls.encoded = base64.b64encode((root / 'fixture.p12').read_bytes()).decode()
        archive = root / 'tool.tar.gz'
        with tarfile.open(archive, 'w:gz') as package:
            data = b'fixture executable'
            member = tarfile.TarInfo('apple-codesign/rcodesign')
            member.size = len(data)
            package.addfile(member, io.BytesIO(data))
        cls.archive = archive

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='snow release test ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / 'github-env'
        self.environment = mock.patch.dict(os.environ, {
            'RUNNER_TEMP': str(self.root), 'GITHUB_ENV': str(self.output),
            'MACOS_SIGNING_P12_BASE64': self.encoded,
            'MACOS_SIGNING_P12_PASSWORD': self.password,
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def prepare(self, bad_checksum=False):
        original_run = signing.run
        calls = []

        def run(args):
            calls.append(args)
            if args[0] == 'curl':
                shutil.copyfile(self.archive, args[-1])
                return ''
            if Path(args[0]).name == 'rcodesign':
                return 'rcodesign 0.29.0'
            return original_run(args)

        digest = '0' * 64 if bad_checksum else hashlib.sha256(self.archive.read_bytes()).hexdigest()
        with mock.patch.object(signing, 'run', side_effect=run), \
                mock.patch.object(signing, 'SHA256', digest), \
                mock.patch.object(signing, 'probe') as native_probe, \
                contextlib.redirect_stdout(io.StringIO()):
            signing.prepare()
            native_probe.assert_called_once()
        return dict(line.split('=', 1) for line in self.output.read_text().splitlines()), calls

    def bundle(self, identifier='com.snowshot.snow_shot'):
        app = self.root / ('Snow Shot Mini.app' if identifier.endswith('_mini') else 'Snow Shot.app')
        executable = signing.PRODUCTS[identifier]
        runtime = app / 'Contents/MacOS'
        runtime.mkdir(parents=True)
        (runtime / executable).write_bytes(b'main executable')
        (runtime / 'snow-ocr-process').write_bytes(b'preserve signed helper bytes')
        (app / 'Contents/Resources').mkdir()
        (app / 'Contents/Resources/ocr-manifest.json').write_bytes(b'preserve manifest bytes')
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': identifier, 'CFBundleExecutable': executable}))
        return app, executable

    def test_prepare_validates_p12_and_keeps_secrets_out_of_exports(self):
        paths, _ = self.prepare()
        self.assertNotIn(self.password, self.output.read_text())
        self.assertNotIn(self.encoded, self.output.read_text())
        for key in ('SNOW_SIGNING_P12', 'SNOW_SIGNING_PASSWORD_FILE'):
            self.assertEqual(Path(paths[key]).stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(paths['SNOW_SIGNING_DIRECTORY']).stat().st_mode & 0o777, 0o700)
        with mock.patch.dict(os.environ, paths):
            signing.cleanup()
            signing.cleanup()
        self.assertFalse(Path(paths['SNOW_SIGNING_DIRECTORY']).exists())

    def test_missing_secrets_fail_before_creating_files(self):
        os.environ.pop('MACOS_SIGNING_P12_PASSWORD')
        with self.assertRaisesRegex(RuntimeError, 'Configure MACOS_SIGNING'):
            signing.prepare()
        self.assertFalse(list(self.root.glob('snow-release-signing-*')))

    def test_checksum_failure_cleans_material_and_does_not_export_paths(self):
        with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
            self.prepare(bad_checksum=True)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('snow-release-signing-*')))

    def test_wrong_password_fails_before_downloading_tools(self):
        os.environ['MACOS_SIGNING_P12_PASSWORD'] = 'incorrect-test-password'
        with self.assertRaisesRegex(RuntimeError, 'openssl failed'):
            signing.prepare()
        self.assertFalse(list(self.root.glob('snow-release-signing-*')))

    def test_native_probe_failure_cleans_material_before_export(self):
        # prepare() must not expose a broken signing state to later CPack jobs.
        original_run = signing.run

        def run(args):
            if args[0] == 'curl':
                shutil.copyfile(self.archive, args[-1])
                return ''
            if Path(args[0]).name == 'rcodesign':
                return 'rcodesign 0.29.0'
            return original_run(args)

        with mock.patch.object(signing, 'run', side_effect=run), \
                mock.patch.object(signing, 'SHA256', hashlib.sha256(self.archive.read_bytes()).hexdigest()), \
                mock.patch.object(signing, 'probe', side_effect=RuntimeError('native probe failed')):
            with self.assertRaisesRegex(RuntimeError, 'native probe failed'):
                signing.prepare()
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('snow-release-signing-*')))

    def exercise_signature(self, identifier, mutate_helper=False, bad_requirement=False,
                           rejected_certificate=False):
        paths, _ = self.prepare()
        app, executable = self.bundle(identifier)
        before = signing.resources(app, executable)
        calls = []

        def run(args):
            calls.append(list(map(str, args)))
            if Path(args[0]).name == 'lipo':
                return 'arm64\n'
            if args[1] == 'sign':
                self.assertEqual(args[args.index('--exclude') + 1], '**')
                (app / 'Contents/MacOS' / executable).write_bytes(b'signed main executable')
                seal = app / 'Contents/_CodeSignature/CodeResources'
                seal.parent.mkdir()
                seal.write_bytes(b'new resource seal')
                if mutate_helper:
                    (app / 'Contents/MacOS/snow-ocr-process').write_bytes(b'wrong helper')
            if '-r-' in args:
                if bad_requirement:
                    return 'designated => cdhash H"1234"'
                return f'designated => identifier "{identifier}" and certificate root = H"0123"'
            if '-R' in args:
                if rejected_certificate:
                    raise RuntimeError('codesign failed: certificate requirement rejected')
                fingerprint = Path(paths['SNOW_SIGNING_CERTIFICATE_SHA1_FILE']).read_text()
                self.assertIn('certificate leaf = H"' + fingerprint + '"', args[-2])
            return ''

        with mock.patch.dict(os.environ, paths), mock.patch.object(signing, 'run', side_effect=run), \
                contextlib.redirect_stdout(io.StringIO()):
            signing.sign(app, 'arm64')
        self.assertEqual(signing.resources(app, executable), before)
        self.assertTrue(any('--deep' in args for args in calls))
        self.assertTrue(any('-R' in args for args in calls))

    def test_full_and_mini_keep_identity_and_nested_resources(self):
        for identifier in signing.PRODUCTS:
            with self.subTest(identifier=identifier):
                # Each prepare consumes and removes the secret variables.
                os.environ['MACOS_SIGNING_P12_BASE64'] = self.encoded
                os.environ['MACOS_SIGNING_P12_PASSWORD'] = self.password
                self.exercise_signature(identifier)

    def test_changed_ocr_helper_aborts_packaging(self):
        with self.assertRaisesRegex(RuntimeError, 'changed nested code'):
            self.exercise_signature('com.snowshot.snow_shot', mutate_helper=True)

    def test_ad_hoc_requirement_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'stable certificate-based'):
            self.exercise_signature('com.snowshot.snow_shot', bad_requirement=True)

    def test_apple_certificate_verification_failure_is_fatal(self):
        with self.assertRaisesRegex(RuntimeError, 'certificate requirement rejected'):
            self.exercise_signature('com.snowshot.snow_shot', rejected_certificate=True)

    def test_cpack_hook_requires_signing_when_enabled(self):
        app, _ = self.bundle()
        app.rename(self.root / 'snow_shot.app')
        with mock.patch.dict(os.environ, {'SNOW_REQUIRE_RELEASE_SIGNATURE': '1',
                                         'SNOW_RELEASE_SIGNING_ARCH': 'arm64'}):
            os.environ.pop('SNOW_SIGNING_CERTIFICATE_SHA1_FILE', None)
            result = subprocess.run(['cmake', '-DCPACK_TEMPORARY_DIRECTORY=' + str(self.root),
                                     '-P', str(ROOT / 'cmake/PrepareSnowShotMacOSDmg.cmake')],
                                    text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Release signing failed', result.stderr)


if __name__ == '__main__':
    unittest.main()
