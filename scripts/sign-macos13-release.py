"""Fixed-P12 release signing, using the same rcodesign version as paste-rs.

Secrets are read only by `prepare`. Only temporary file paths reach CPack.
"""

import argparse
import base64
import hashlib
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


VERSION = '0.29.0'
SHA256 = 'd98372d5524226ccf9dc0eda03d4e4f5826182dabb2fc3f2bd303ed9113a748d'
URL = ('https://github.com/indygreg/apple-platform-rs/releases/download/'
       f'apple-codesign%2F{VERSION}/apple-codesign-{VERSION}-macos-universal.tar.gz')
PRODUCTS = {'com.snowshot.snow_shot': 'snow_shot',
            'com.snowshot.snow_shot_mini': 'snow_shot_mini'}


def run(args):
    result = subprocess.run(list(map(str, args)), text=True, capture_output=True)
    if result.returncode:
        # No secret values are passed as command arguments.
        raise RuntimeError(f'{Path(args[0]).name} failed: {result.stderr.strip()}')
    return result.stdout + result.stderr


def prepare():
    encoded = os.environ.pop('MACOS_SIGNING_P12_BASE64', '')
    password = os.environ.pop('MACOS_SIGNING_P12_PASSWORD', '')
    if not encoded or not password:
        raise RuntimeError('Configure MACOS_SIGNING_P12_BASE64 and '
                           'MACOS_SIGNING_P12_PASSWORD in repository Actions Secrets')
    material = base64.b64decode(encoded, validate=True)
    root = Path(tempfile.mkdtemp(prefix='snow-release-signing-', dir=os.environ['RUNNER_TEMP']))
    try:
        for name, data in [('identity.p12', material), ('password', password.encode())]:
            with (root / name).open('xb') as stream:
                os.chmod(stream.name, 0o600)
                stream.write(data)
        cert = root / 'certificate.pem'
        run(['openssl', 'pkcs12', '-in', root / 'identity.p12',
             '-passin', 'file:' + str(root / 'password'), '-clcerts', '-nokeys', '-out', cert])
        run(['openssl', 'x509', '-in', cert, '-checkend', '0', '-noout'])
        fingerprint = run(['openssl', 'x509', '-in', cert, '-noout', '-fingerprint', '-sha1'])
        fingerprint = fingerprint.strip().split('=')[-1].replace(':', '').upper()
        if not re.fullmatch('[0-9A-F]{40}', fingerprint):
            raise RuntimeError('Could not determine the signing certificate fingerprint')
        (root / 'certificate.sha1').write_text(fingerprint)
        archive = root / 'rcodesign.tar.gz'
        run(['curl', '--fail', '--show-error', '--location', '--retry', '3', URL, '-o', archive])
        if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
            raise RuntimeError('rcodesign archive checksum mismatch')
        with tarfile.open(archive) as package:
            members = [m for m in package.getmembers()
                       if m.isfile() and Path(m.name).name == 'rcodesign']
            if len(members) != 1:
                raise RuntimeError('Expected exactly one rcodesign executable')
            with package.extractfile(members[0]) as source, (root / 'rcodesign').open('xb') as dest:
                shutil.copyfileobj(source, dest)
        (root / 'rcodesign').chmod(0o700)
        run([root / 'rcodesign', '--version'])
        paths = {'SNOW_SIGNING_DIRECTORY': root, 'SNOW_RCODESIGN': root / 'rcodesign',
                 'SNOW_SIGNING_P12': root / 'identity.p12',
                 'SNOW_SIGNING_PASSWORD_FILE': root / 'password',
                 'SNOW_SIGNING_CERTIFICATE_SHA1_FILE': root / 'certificate.sha1'}
        probe(paths)
        with open(os.environ['GITHUB_ENV'], 'a') as stream:
            for name, value in paths.items():
                stream.write(f'{name}={value}\n')
    except BaseException:
        shutil.rmtree(root)
        raise
    print('Prepared fixed release signing identity; private material remains in runner temp')


def resources(app, executable):
    snapshot = {}
    for path in app.rglob('*'):
        relative = path.relative_to(app).as_posix()
        if relative == f'Contents/MacOS/{executable}' or relative.startswith('Contents/_CodeSignature/'):
            continue
        if path.is_symlink():
            snapshot[relative] = ('link', os.readlink(path))
        elif path.is_file():
            with path.open('rb') as stream:
                snapshot[relative] = ('file', hashlib.file_digest(stream, 'sha256').hexdigest())
    return snapshot


def sign(app, arch, configuration=None):
    configuration = os.environ if configuration is None else configuration
    app = Path(app).resolve(strict=True)
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    identifier = info.get('CFBundleIdentifier')
    executable = PRODUCTS.get(identifier)
    if not executable or info.get('CFBundleExecutable') != executable:
        raise RuntimeError('Unexpected Snow Shot bundle identifier/executable')
    binary = app / 'Contents/MacOS' / executable
    if binary.is_symlink() or not binary.is_file():
        raise RuntimeError('Main executable must be a regular file')
    fingerprint = Path(configuration['SNOW_SIGNING_CERTIFICATE_SHA1_FILE']).read_text().strip()
    if not re.fullmatch('[0-9A-F]{40}', fingerprint):
        raise RuntimeError('Invalid expected certificate fingerprint')
    expected_arch = {'arm64': 'arm64', 'x64': 'x86_64'}[arch]
    if run(['/usr/bin/lipo', '-archs', binary]).strip() != expected_arch:
        raise RuntimeError('Bundle architecture differs from the release target')
    before = resources(app, executable)
    # --exclude '**' is rcodesign's documented shallow-signing mode. Preserve
    # every nested Mach-O and the already-finalized OCR manifest byte for byte.
    run([configuration['SNOW_RCODESIGN'], 'sign',
         '--p12-file', configuration['SNOW_SIGNING_P12'],
         '--p12-password-file', configuration['SNOW_SIGNING_PASSWORD_FILE'],
         '--exclude', '**', app])
    if resources(app, executable) != before:
        raise RuntimeError('Signing changed nested code or resources; refusing to package')
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app])
    requirement = run(['/usr/bin/codesign', '-d', '-r-', app])
    if ('designated =>' not in requirement or 'cdhash' in requirement.lower()
            or 'certificate' not in requirement
            or f'identifier "{identifier}"' not in requirement):
        raise RuntimeError('Release requires a stable certificate-based designated requirement')
    run(['/usr/bin/codesign', '--verify', '--strict', '-R',
         f'=identifier "{identifier}" and certificate leaf = H"{fingerprint}"', app])
    print(f'Verified stable release identity: {identifier}, certificate {fingerprint}')
    print(requirement.strip())


def probe(paths):
    """Exercise real Apple verification before paying for the application build."""
    arch = os.environ['SNOW_RELEASE_SIGNING_ARCH']
    native_arch = {'arm64': 'arm64', 'x64': 'x86_64'}[arch]
    with tempfile.TemporaryDirectory(prefix='probe-', dir=paths['SNOW_SIGNING_DIRECTORY']) as temporary:
        root = Path(temporary)
        source = root / 'main.c'
        source.write_text('int main(void) { return 0; }\n')
        executable = root / 'probe'
        run(['/usr/bin/xcrun', 'clang', '-arch', native_arch, '-mmacosx-version-min=13.0',
             source, '-o', executable])
        run(['/usr/bin/codesign', '--force', '--sign', '-', executable])
        for identifier, name in PRODUCTS.items():
            app = root / (name + '.app')
            runtime = app / 'Contents/MacOS'
            runtime.mkdir(parents=True)
            (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': identifier, 'CFBundleExecutable': name,
                'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1'}))
            shutil.copy2(executable, runtime / name)
            shutil.copy2(executable, runtime / 'snow-ocr-process')
            (runtime / 'assets').mkdir()
            (runtime / 'assets/manifest.json').write_text('{"fixture":true}\n')
            sign(app, arch, paths)
    print('Native Full/Mini signing and nested-helper preservation probes passed')


def cleanup():
    name = os.environ.get('SNOW_SIGNING_DIRECTORY')
    if not name:
        return
    path = Path(name)
    temporary = Path(os.environ['RUNNER_TEMP']).resolve()
    if (path.is_symlink() or path.parent.resolve() != temporary
            or not path.name.startswith('snow-release-signing-')):
        raise RuntimeError('Refusing to clean an unexpected signing directory')
    if path.exists():
        shutil.rmtree(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'sign', 'cleanup'])
    parser.add_argument('--app', type=Path)
    parser.add_argument('--arch', choices=['arm64', 'x64'])
    args = parser.parse_args()
    if args.command == 'sign':
        if not args.app or not args.arch:
            parser.error('sign requires --app and --arch')
        sign(args.app, args.arch)
    elif args.command == 'prepare':
        prepare()
    else:
        cleanup()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, tarfile.TarError) as error:
        sys.exit(f'Release signing failed: {error}')
