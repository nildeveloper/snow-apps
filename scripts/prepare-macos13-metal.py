"""Validate and prepare the pinned OCR Metal source for compatibility builds.

The only accepted working-tree states are the recorded original file and its
exact compatibility-patched form. Never overwrite unrelated local edits.
"""

from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SUBMODULE = 'snow-crates/crates/simd-paddle-ocr-rs'
SOURCE = 'src/runtime/gpu/metal/build.rs'


def git(directory, *args):
    return subprocess.check_output(['git', '-C', str(directory), *args])


def probe(root):
    subprocess.run([sys.executable, str(root / 'scripts/check-macos13-metal-toolchain.py')],
                   check=True)


def prepare(root, check_toolchain=probe):
    root = Path(root).resolve()
    ocr = root / SUBMODULE
    entry = git(root, 'ls-tree', 'HEAD', '--', SUBMODULE).decode().split()
    if len(entry) != 4 or entry[:2] != ['160000', 'commit']:
        raise RuntimeError('The OCR dependency must be a recorded Git submodule')
    if git(ocr, 'rev-parse', 'HEAD').decode().strip() != entry[2]:
        raise RuntimeError('OCR checkout differs from the recorded submodule commit; '
                           'initialize/update the pinned submodule before building')
    source = ocr / SOURCE
    if source.is_symlink():
        raise RuntimeError('Refusing a symlinked OCR Metal build script')
    original = git(ocr, 'show', 'HEAD:' + SOURCE)
    patch = root / 'cmake/ocr/macos13-metal-tt.patch'
    # Validate against the committed source, not a possibly half-patched tree.
    # Work outside the repository so git apply cannot touch other checkout files.
    with tempfile.TemporaryDirectory(prefix='snow-metal-prepare-') as temporary:
        staged = Path(temporary) / SOURCE
        staged.parent.mkdir(parents=True)
        staged.write_bytes(original)
        for options in (['--check'], []):
            subprocess.run(['git', 'apply', *options, str(patch)], cwd=temporary, check=True)
        patched = staged.read_bytes()
    current = source.read_bytes()
    if current not in (original, patched):
        raise RuntimeError('OCR Metal build script has local changes; refusing to overwrite them')
    # A missing/broken toolchain must fail before modifying the working tree.
    check_toolchain(root)
    if source.read_bytes() != current:
        raise RuntimeError('OCR Metal source changed during the toolchain probe; retry after review')
    if current == patched:
        print('OCR Metal compatibility patch already applied; source unchanged')
        return False
    source.write_bytes(patched)
    print('Applied OCR Metal compatibility patch to the submodule working tree '
          '(recorded commit unchanged)')
    return True


if __name__ == '__main__':
    try:
        prepare(ROOT)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f'Metal compatibility preparation failed: {error}')
