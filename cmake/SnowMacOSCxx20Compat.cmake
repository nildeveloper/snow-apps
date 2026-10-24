include_guard(GLOBAL)

function(snow_configure_macos_cxx20_compat)
    if(NOT APPLE)
        return()
    endif()

    include(CheckCXXSourceCompiles)
    set(_snow_saved_required_flags "${CMAKE_REQUIRED_FLAGS}")
    set(CMAKE_REQUIRED_FLAGS "${CMAKE_REQUIRED_FLAGS} -std=c++20")
    check_cxx_source_compiles(
        "#include <stop_token>\n#include <thread>\nint main() { std::stop_source source; std::jthread worker([](std::stop_token) {}); return source.request_stop() ? 0 : 0; }"
        SNOW_MACOS_HAS_NATIVE_JTHREAD
    )
    set(CMAKE_REQUIRED_FLAGS "${_snow_saved_required_flags}")
    unset(_snow_saved_required_flags)

    if(SNOW_MACOS_HAS_NATIVE_JTHREAD)
        return()
    endif()

    find_path(SNOW_JTHREAD_BACKPORT_INCLUDE_DIR
        NAMES jthread.hpp stop_token.hpp
        REQUIRED
    )

    set(_snow_compat_dir "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/macos-cxx20-compat")
    include_directories(BEFORE SYSTEM
        "${_snow_compat_dir}"
        "${SNOW_JTHREAD_BACKPORT_INCLUDE_DIR}"
    )
    add_compile_options(
        "$<$<COMPILE_LANGUAGE:CXX>:-include>"
        "$<$<COMPILE_LANGUAGE:CXX>:${_snow_compat_dir}/preinclude.h>"
    )

    message(STATUS
        "Apple libc++ lacks std::stop_token/std::jthread; using josuttis-jthread compatibility headers")
endfunction()
