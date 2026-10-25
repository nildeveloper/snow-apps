#pragma once

// This file is force-included only after CMake has proved that the selected
// Apple libc++ cannot provide a usable std::jthread/std::stop_token pair.
// Keep the fallback self-contained: mixing libc++'s partial <stop_token>
// implementation with josuttis-jthread defines conflicting std internals.
#include <jthread.hpp>
