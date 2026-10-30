"""Focused source-boundary probes, not a replacement for the full native build.

The export probe compiles the actual fields, constructor and forwarding expression
with minimal Qt stand-ins. On macOS the screen adapter is also syntax-checked
against the real SDK, with Qt stand-ins and a macOS 13 deployment target.
"""

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / 'snow_shot/src/presentation/imageediting/imageeditingexportcontroller'
SCREEN = ROOT / 'snow_shot/src/platform/macos/qtscreencompat_p.h'
GEOMETRY = ROOT / 'snow_shot/src/presentation/core/screenshotgeometry.cpp'


def compiler_command():
    configured = os.environ.get('CXX')
    if configured:
        command = shlex.split(configured)
    else:
        compiler = shutil.which('clang++') or shutil.which('c++')
        command = [compiler] if compiler else []
    if not command or not shutil.which(command[0]):
        raise RuntimeError('A C++ compiler is required for the compatibility source probe')
    return command


def export_probe(source, header):
    # Read production declarations, rather than a separately maintained constructor.
    impl_marker = 'struct ImageEditingExportController::Impl {'
    fields = source.split(impl_marker, 1)[1].split('    void finish(', 1)[0]
    constructor_start = source.index('ImageEditingExportController::ImageEditingExportController(')
    constructor_end = source.index('ImageEditingExportController::~ImageEditingExportController()',
                                   constructor_start)
    constructor = source[constructor_start:constructor_end]
    pin_alias = re.search(r'using Pin\s*=.*?;', header, re.S).group(0)
    declaration = re.search(r'explicit ImageEditingExportController\(.*?\);', header, re.S).group(0)
    return '''#include <cassert>
#include <functional>
#include <memory>
#include <utility>
struct QImage { int marker = 0; };
struct QObject { explicit QObject(QObject* = nullptr) {} };
struct ScreenshotPrintService {};
struct Request {};
template <typename T> struct QPointer {
    explicit operator bool() const { return false; }
};
class ImageEditingExportController : public QObject {
  public:
    ''' + pin_alias + '\n    ' + declaration + '''
    ~ImageEditingExportController();
    void verify(ScreenshotPrintService* expected, bool hasPin);
  private:
    struct Impl;
    std::unique_ptr<Impl> m_impl;
};
''' + impl_marker + fields + '\n};\n' + constructor + '''
ImageEditingExportController::~ImageEditingExportController() = default;
void ImageEditingExportController::verify(ScreenshotPrintService* expected, bool hasPin) {
    assert(&m_impl->q == this);
    assert(m_impl->printing == expected);
    assert(!m_impl->active);
    assert(static_cast<bool>(m_impl->pin) == hasPin);
    if (hasPin) {
        bool completed = false;
        assert(m_impl->pin(QImage{42}, [&](bool ok) { completed = ok; }));
        assert(completed);
    }
}
int main() {
    ScreenshotPrintService printing;
    int invoked = 0;
    ImageEditingExportController controller(&printing, nullptr,
        [&](QImage image, std::function<void(bool)> completion) {
            assert(image.marker == 42);
            ++invoked;
            completion(true);
            return true;
        });
    controller.verify(&printing, true);
    assert(invoked == 1);
    ImageEditingExportController withoutPin(nullptr, nullptr);
    withoutPin.verify(nullptr, false);
}
'''


class ExportConstructor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = EDITOR.with_suffix('.cpp').read_text()
        cls.header = EDITOR.with_suffix('.h').read_text()
        cls.compiler = compiler_command()

    def compile_probe(self, source, directory):
        path = directory / 'export-probe.cpp'
        path.write_text(export_probe(source, self.header))
        return subprocess.run(self.compiler + ['-std=c++20', '-Wall', '-Wextra', '-Werror',
                              '-pedantic', str(path), '-o', str(directory / 'export-probe')],
                              text=True, capture_output=True, timeout=60)

    def test_production_constructor_preserves_pin_and_default_state(self):
        with tempfile.TemporaryDirectory(prefix='snow export probe ') as temporary:
            directory = Path(temporary)
            result = self.compile_probe(self.source, directory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(directory / 'export-probe')], text=True,
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_probe_rejects_the_previous_two_argument_constructor(self):
        broken = self.source.replace(', Pin pinHandler)', ')', 1)
        broken = broken.replace(', pin(std::move(pinHandler))', '', 1)
        self.assertNotEqual(broken, self.source, 'review this fixture after constructor changes')
        with tempfile.TemporaryDirectory(prefix='snow export mutation ') as temporary:
            result = self.compile_probe(broken, Path(temporary))
            self.assertNotEqual(result.returncode, 0, 'the old merge regression must not compile')

    def test_probe_rejects_dropping_the_pin_argument(self):
        broken = self.source.replace('(*this, printing, std::move(pin))', '(*this, printing)', 1)
        self.assertNotEqual(broken, self.source, 'review this fixture after constructor changes')
        with tempfile.TemporaryDirectory(prefix='snow export mutation ') as temporary:
            result = self.compile_probe(broken, Path(temporary))
            self.assertNotEqual(result.returncode, 0, 'dropping the pin callback is not a fix')


class ScreenCompatibility(unittest.TestCase):
    def test_geometry_uses_the_platform_boundary(self):
        source = GEOMETRY.read_text()
        self.assertIn('#include "../../platform/macos/qtscreencompat_p.h"', source)
        self.assertNotIn('#import <AppKit/AppKit.h>', source)
        self.assertNotIn('NSScreen.screens', source)
        self.assertNotIn('QNativeInterface::QCocoaScreen', source)
        for name in ('macNativeDisplayId', 'macScreenForDisplayId'):
            self.assertIn('using snow_shot::platform::qt_screen_compat::' + name + ';', source)
            self.assertIn(name + '(', SCREEN.read_text())

    @unittest.skipUnless(sys.platform == 'darwin', 'requires the real macOS SDK')
    def test_adapter_compiles_against_macos13_sdk_apis(self):
        # Qt stand-ins avoid bootstrapping all Qt just for an AppKit API probe.
        # This validates SDK availability/syntax, not Qt ABI or monitor behavior.
        compiler = subprocess.check_output(['xcrun', '--find', 'clang++'], text=True).strip()
        sdk = subprocess.check_output(
            ['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
        with tempfile.TemporaryDirectory(prefix='snow screen probe ') as temporary:
            directory = Path(temporary)
            (directory / 'QRectF').write_text('''#pragma once
struct QRectF {
    QRectF() = default;
    QRectF(double, double, double, double) {}
    bool operator!=(const QRectF&) const { return false; }
};
''')
            (directory / 'QScreen').write_text('''#pragma once
#include <QRectF>
struct QScreen { QRectF geometry() const { return {}; } };
''')
            (directory / 'QGuiApplication').write_text('''#pragma once
#include <QScreen>
#include <vector>
struct QGuiApplication { static std::vector<QScreen*> screens() { return {}; } };
''')
            probe = directory / 'screen-probe.mm'
            probe.write_text('#include "' + str(SCREEN) + '"\n')
            result = subprocess.run([compiler, '-std=c++20', '-fsyntax-only', '-fblocks',
                                     '-Wall', '-Wextra', '-Werror',
                                     '-Werror=unguarded-availability-new',
                                     '-mmacosx-version-min=13.0', '-isysroot', sdk,
                                     '-I', str(directory), str(probe)],
                                    text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


@unittest.skipIf(sys.platform == 'darwin', 'native preflight tests the real macOS backport')
class StopAwareWait(unittest.TestCase):
    def test_native_and_fallback_cancellation_contract(self):
        with tempfile.TemporaryDirectory(prefix='snow stop wait ') as temporary:
            executable = Path(temporary) / 'stop-wait-tests'
            result = subprocess.run(
                compiler_command() + ['-std=c++20', '-Wall', '-Wextra', '-Werror', '-pedantic',
                                      '-pthread', '-I', str(ROOT / 'snow_image/include'),
                                      str(ROOT / 'test-support/macos-build/stop_wait_tests.cpp'),
                                      '-o', str(executable)],
                text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(executable)], text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
