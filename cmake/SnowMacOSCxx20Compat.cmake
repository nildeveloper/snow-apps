include_guard(GLOBAL)

function(snow_configure_macos_cxx20_compat)
    if(NOT APPLE)
        return()
    endif()

    include(CheckCXXSourceCompiles)
    set(_snow_jthread_probe
        "#include <stop_token>\n#include <thread>\nint main() { std::stop_source source; std::jthread worker([](std::stop_token) {}); return source.request_stop() ? 0 : 0; }")

    set(_snow_saved_required_flags "${CMAKE_REQUIRED_FLAGS}")
    set(CMAKE_REQUIRED_FLAGS "${CMAKE_REQUIRED_FLAGS} -std=c++20")
    check_cxx_source_compiles(
        "${_snow_jthread_probe}"
        SNOW_MACOS_HAS_NATIVE_JTHREAD
    )
    set(CMAKE_REQUIRED_FLAGS "${_snow_saved_required_flags}")
    unset(_snow_saved_required_flags)
    unset(_snow_jthread_probe)

    if(SNOW_MACOS_HAS_NATIVE_JTHREAD)
        return()
    endif()

    find_path(SNOW_JTHREAD_BACKPORT_INCLUDE_DIR
        NAMES jthread.hpp stop_token.hpp
        REQUIRED
    )

    # Xcode 16.x ships libc++ stop-token implementation details even though the
    # public C++20 API is still unavailable for this deployment target. The
    # josuttis backport uses the same reserved internal names, which makes the
    # two implementations ambiguous as soon as <thread> pulls libc++ internals
    # into namespace std. Generate an isolated copy with project-private
    # internal names while keeping the standardized public API unchanged.
    set(_snow_generated_dir
        "${CMAKE_BINARY_DIR}/snow-macos-cxx20-compat")
    file(MAKE_DIRECTORY "${_snow_generated_dir}")

    file(READ
        "${SNOW_JTHREAD_BACKPORT_INCLUDE_DIR}/stop_token.hpp"
        _snow_stop_token_header)
    string(REPLACE "__spin_yield" "__snow_spin_yield"
        _snow_stop_token_header "${_snow_stop_token_header}")
    string(REPLACE "__stop_callback_base" "__snow_stop_callback_base"
        _snow_stop_token_header "${_snow_stop_token_header}")
    string(REPLACE "__stop_state" "__snow_stop_state"
        _snow_stop_token_header "${_snow_stop_token_header}")
    file(WRITE
        "${_snow_generated_dir}/stop_token.hpp"
        "${_snow_stop_token_header}")
    configure_file(
        "${SNOW_JTHREAD_BACKPORT_INCLUDE_DIR}/jthread.hpp"
        "${_snow_generated_dir}/jthread.hpp"
        COPYONLY
    )
    unset(_snow_stop_token_header)

    set(_snow_compat_dir
        "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/macos-cxx20-compat")
    include_directories(BEFORE SYSTEM
        "${_snow_compat_dir}"
        "${_snow_generated_dir}"
    )
    add_compile_options(
        "$<$<COMPILE_LANGUAGE:CXX>:-include>"
        "$<$<COMPILE_LANGUAGE:CXX>:${_snow_compat_dir}/preinclude.h>"
    )

    message(STATUS
        "Apple libc++ lacks public std::stop_token/std::jthread; using isolated josuttis-jthread compatibility headers")
endfunction()
