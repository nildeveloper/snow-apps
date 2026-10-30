// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <chrono>
#include <stop_token>

namespace snow::image::detail {

// Older Apple libc++ can use the stop-token backport without providing the
// condition-variable overload. Poll only on that path: a bare stop_callback
// notification can be lost between the predicate check and entering wait.
template <typename Condition, typename Lock, typename Predicate>
bool stop_aware_wait(Condition& condition, Lock& lock, std::stop_token stop, Predicate predicate) {
    if constexpr (requires { condition.wait(lock, stop, predicate); }) {
        return condition.wait(lock, stop, predicate);
    } else {
        while (!predicate()) {
            if (stop.stop_requested()) {
                return predicate();
            }
            condition.wait_for(lock, std::chrono::milliseconds(10),
                               [&] { return stop.stop_requested() || predicate(); });
        }
        return true;
    }
}

} // namespace snow::image::detail
