#!/usr/bin/env python3
"""Build a tiny Full/Mini fixture using the production diagnostics CMake block."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]


class DiagnosticsCompileScope(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("cmake") and shutil.which("c++") and shutil.which("make"),
        "requires CMake, C++ and Make",
    )
    def test_identity_only_invalidates_main_in_full_and_mini(self):
        app_cmake = (REPOSITORY / "snow_shot/CMakeLists.txt").read_text()
        block = re.search(
            r'target_compile_definitions\(snow_shot PRIVATE QT_MESSAGELOGCONTEXT\)'
            r'.*?set_property\(SOURCE src/app/main\.cpp APPEND PROPERTY COMPILE_DEFINITIONS'
            r'.*?SNOW_DIAGNOSTICS_BUILD="\$<CONFIG>"\)', app_cmake, re.S)
        self.assertIsNotNone(block)
        self.assertIn('include("${CMAKE_CURRENT_SOURCE_DIR}/../cmake/SnowShotMini.cmake")',
                      app_cmake)
        mini_cmake = (REPOSITORY / "cmake/SnowShotMini.cmake").read_text()
        copy_properties = re.search(
            r'function\(_snow_mini_copy_build_properties original target\).*?endfunction\(\)',
            mini_cmake, re.S)
        self.assertIsNotNone(copy_properties)
        self.assertIn('get_target_property(_sources snow_shot SOURCES)', mini_cmake)
        self.assertIn('qt_add_executable(snow_shot_mini MANUAL_FINALIZATION ${_sources})',
                      mini_cmake)
        self.assertIn('_snow_mini_copy_build_properties(snow_shot snow_shot_mini)', mini_cmake)
        with tempfile.TemporaryDirectory(prefix="snow-diagnostics-scope-") as temporary:
            root = Path(temporary)
            app = root / "app"
            (app / "src/app").mkdir(parents=True)
            (app / "src/app/main.cpp").write_text('''
#ifndef QT_MESSAGELOGCONTEXT
#error missing logging context
#endif
#ifndef SNOW_DIAGNOSTICS_VERSION
#error missing version
#endif
#ifndef SNOW_DIAGNOSTICS_REVISION
#error missing revision
#endif
#ifndef SNOW_DIAGNOSTICS_BUILD
#error missing configuration
#endif
#include <iostream>
int main() {
    std::cout << SNOW_DIAGNOSTICS_VERSION << ":" << SNOW_DIAGNOSTICS_REVISION
              << ":" << SNOW_DIAGNOSTICS_BUILD;
}
''')
            (app / "unrelated.cpp").write_text('''
#ifndef QT_MESSAGELOGCONTEXT
#error missing logging context
#endif
#if defined(SNOW_DIAGNOSTICS_VERSION) || defined(SNOW_DIAGNOSTICS_REVISION) || defined(SNOW_DIAGNOSTICS_BUILD)
#error app identity leaked to unrelated source
#endif
int unrelated() { return 42; }
''')
            (root / "CMakeLists.txt").write_text('''
cmake_minimum_required(VERSION 3.30)
project(DiagnosticsScope LANGUAGES CXX)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
add_subdirectory(app)
''')
            (app / "CMakeLists.txt").write_text('''
add_executable(snow_shot src/app/main.cpp unrelated.cpp)
''' + block.group() + '''
function(snow_shot_set_source_dependency_edition)
endfunction()
function(_snow_mini_rewrite out value)
    set(${out} "${value}" PARENT_SCOPE)
endfunction()
''' + copy_properties.group() + '''
get_target_property(_sources snow_shot SOURCES)
add_executable(snow_shot_mini ${_sources})
_snow_mini_copy_build_properties(snow_shot snow_shot_mini)
''')
            build = root / "build"
            commands = []
            for version, revision in [("1.4.4", "revision-one"), ("1.4.5", "revision-two")]:
                subprocess.run([
                    "cmake", "-S", str(root), "-B", str(build), "-G", "Unix Makefiles",
                    "-DCMAKE_BUILD_TYPE=Release", f"-DSNOW_SHOT_VERSION={version}",
                    f"-DSNOW_DIAGNOSTICS_REVISION={revision}",
                ], check=True, capture_output=True, text=True)
                subprocess.run(["cmake", "--build", str(build)], check=True,
                               capture_output=True, text=True)
                commands.append(json.loads((build / "compile_commands.json").read_text()))
                for target in ["snow_shot", "snow_shot_mini"]:
                    result = subprocess.run([str(build / "app" / target)], check=True,
                                            capture_output=True, text=True)
                    self.assertEqual(result.stdout, f"{version}:{revision}:Release")
            for filename in ["main.cpp", "unrelated.cpp"]:
                before = [c["command"] for c in commands[0] if Path(c["file"]).name == filename]
                after = [c["command"] for c in commands[1] if Path(c["file"]).name == filename]
                self.assertEqual(len(before), 2)
                self.assertEqual(len(after), 2)
                if filename == "main.cpp":
                    self.assertNotEqual(before, after)
                else:
                    self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
