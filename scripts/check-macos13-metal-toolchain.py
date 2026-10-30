"""Compile a tiny native Metal archive before the expensive release build.

Requires macOS with the selected Xcode/Metal toolchain. This checks build-tool
compatibility; it does not execute GPU kernels or validate OCR correctness.
"""

import json
from pathlib import Path
import subprocess
import tempfile


PIPELINE_DEFAULTS = {
    'threadgroup_size_is_multiple_of_thread_execution_width': False,
    'max_total_threads_per_threadgroup': 0,
    'max_call_stack_depth': 1,
    'support_indirect_command_buffers': False,
    'support_adding_binary_functions': False,
}


def run(*args):
    subprocess.run(['xcrun', '--sdk', 'macosx', *map(str, args)], check=True)


def main():
    sdk = subprocess.check_output(
        ['xcrun', '--sdk', 'macosx', '--show-sdk-version'], text=True)
    major = int(sdk.strip().split('.')[0])
    with tempfile.TemporaryDirectory(prefix='snow-metal-probe-') as directory:
        root = Path(directory)
        source = root / 'probe.metal'
        source.write_text('''#include <metal_stdlib>
using namespace metal;
kernel void snow_probe(device uint* values [[buffer(0)]],
                       uint id [[thread_position_in_grid]]) {
    values[id] += 1;
}
''')
        run('metal', '-std=metal3.1', '-mmacosx-version-min=14.0', '-fno-fast-math',
            '-c', source, '-o', root / 'probe.air')
        run('metallib', root / 'probe.air', '-o', root / 'probe.metallib')
        descriptor = root / 'probe.mtlp-json'
        descriptor.write_text(json.dumps({
            'libraries': {'paths': [{'label': 'OCR', 'path': str(root / 'probe.metallib')}]},
            'pipelines': {'compute_pipelines': [dict(
                PIPELINE_DEFAULTS, compute_function='alias:OCR#snow_probe')]},
        }))
        archive = root / 'probe.binary.metallib'
        run('metal-tt', descriptor, '-target', f'air64-apple-macos{major}.0',
            '-arch', 'applegpu_g16g', '-o', archive)
        if not archive.is_file() or not archive.stat().st_size:
            raise RuntimeError('Metal translator produced no native archive')
    print('Metal shader and native archive probe passed')


if __name__ == '__main__':
    main()
