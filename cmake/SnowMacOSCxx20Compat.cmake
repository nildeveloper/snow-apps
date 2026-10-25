include_guard(GLOBAL)

function(snow_configure_macos_cxx20_compat)
    if(NOT APPLE)
        return()
    endif()

    include(CheckCXXSourceCompiles)
    set(_snow_jthread_probe
        "#include <stop_token>\n#include <thread>\nint main() { std::stop_source source; std::jthread worker([](std::stop_token) {}); return source.request_stop() ? 0 : 0; }")

    set(_snow_saved_required_flags "${CMAKE_REQUIRED_FLAGS}")
    set(_snow_saved_required_link_options "${CMAKE_REQUIRED_LINK_OPTIONS}")
    set(CMAKE_REQUIRED_FLAGS "${CMAKE_REQUIRED_FLAGS} -std=c++20")
    check_cxx_source_compiles(
        "${_snow_jthread_probe}"
        SNOW_MACOS_HAS_NATIVE_JTHREAD
    )

    if(SNOW_MACOS_HAS_NATIVE_JTHREAD)
        set(CMAKE_REQUIRED_FLAGS "${_snow_saved_required_flags}")
        set(CMAKE_REQUIRED_LINK_OPTIONS "${_snow_saved_required_link_options}")
        unset(_snow_saved_required_flags)
        unset(_snow_saved_required_link_options)
        unset(_snow_jthread_probe)
        return()
    endif()

    # AppleClang/Xcode can ship C++20 stop_token/jthread behind libc++'s
    # experimental-library switch. Probe the complete compile+link path before
    # enabling it so macOS 13 back-deployment is verified by the selected SDK.
    set(CMAKE_REQUIRED_FLAGS "${CMAKE_REQUIRED_FLAGS} -fexperimental-library")
    list(APPEND CMAKE_REQUIRED_LINK_OPTIONS -fexperimental-library)
    check_cxx_source_compiles(
        "${_snow_jthread_probe}"
        SNOW_MACOS_HAS_EXPERIMENTAL_JTHREAD
    )
    set(CMAKE_REQUIRED_FLAGS "${_snow_saved_required_flags}")
    set(CMAKE_REQUIRED_LINK_OPTIONS "${_snow_saved_required_link_options}")
    unset(_snow_saved_required_flags)
    unset(_snow_saved_required_link_options)
    unset(_snow_jthread_probe)

    if(SNOW_MACOS_HAS_EXPERIMENTAL_JTHREAD)
        add_compile_options(
            "$<$<COMPILE_LANGUAGE:CXX>:-fexperimental-library>"
        )
        add_link_options(-fexperimental-library)
        message(STATUS
            "Apple libc++ C++20 jthread support requires -fexperimental-library; enabling it")
        return()
    endif()

    if(CMAKE_CXX_COMPILER_ID STREQUAL "AppleClang" AND
       CMAKE_CXX_COMPILER_VERSION VERSION_GREATER_EQUAL "17")
        message(FATAL_ERROR
            "AppleClang ${CMAKE_CXX_COMPILER_VERSION} exposes libc++ stop-token internals "
            "but neither default nor -fexperimental-library jthread support passed the "
            "macOS 13 compile/link probe. Refusing the incompatible header backport.")
    endif()

    # Older Apple toolchains do not expose the libc++ implementation at all.
    # Only those toolchains use the header-only fallback. Keep the fallback
    # isolated from newer libc++ implementations, whose internal stop-token
    # types conflict with the backport.
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
        "Apple libc++ lacks usable std::stop_token/std::jthread; using josuttis-jthread compatibility headers")
endfunction()
