// SPDX-License-Identifier: GPL-3.0-or-later
#include <snow/image/detail/stop_wait.h>

#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <stop_token>
#include <thread>

namespace {
void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

// Deliberately exposes only the pre-C++20 overload, even with a modern STL.
struct PollingCondition {
    std::condition_variable_any condition;
    std::stop_source* cancelBetweenPredicateAndWait = nullptr;
    int waits = 0;

    template <typename Lock, typename Rep, typename Period, typename Predicate>
    bool wait_for(Lock& lock, std::chrono::duration<Rep, Period> timeout, Predicate predicate) {
        ++waits;
        return condition.wait_for(lock, timeout, [&] {
            const bool ready = predicate();
            if (!ready && cancelBetweenPredicateAndWait != nullptr) {
                cancelBetweenPredicateAndWait->request_stop();
                cancelBetweenPredicateAndWait = nullptr;
                // This notification precedes the actual wait. No later notification is sent.
                condition.notify_all();
            }
            return ready;
        });
    }

    void notify_all() {
        condition.notify_all();
    }
};

template <typename Condition> void cancellation_and_completion_contract() {
    Condition condition;
    std::mutex mutex;
    std::unique_lock lock(mutex);
    std::stop_source source;
    source.request_stop();
    require(!snow::image::detail::stop_aware_wait(condition, lock, source.get_token(),
                                                  [] { return false; }),
            "pre-cancelled wait must return false");
    require(snow::image::detail::stop_aware_wait(condition, lock, source.get_token(),
                                                 [] { return true; }),
            "completed predicate must win over cancellation");
    require(lock.owns_lock(), "wait must retain the caller's lock");
}

template <typename Condition> void normal_completion() {
    Condition condition;
    std::mutex mutex;
    bool ready = false;
    std::stop_source source;
    std::thread worker([&] {
        std::unique_lock lock(mutex);
        require(snow::image::detail::stop_aware_wait(condition, lock, source.get_token(),
                                                     [&] { return ready; }),
                "completion must return true");
    });
    {
        std::lock_guard lock(mutex);
        ready = true;
    }
    condition.notify_all();
    worker.join();
}

void cancellation_between_predicate_and_wait() {
    PollingCondition condition;
    std::mutex mutex;
    std::unique_lock lock(mutex);
    std::stop_source source;
    condition.cancelBetweenPredicateAndWait = &source;
    require(!snow::image::detail::stop_aware_wait(condition, lock, source.get_token(),
                                                  [] { return false; }),
            "fallback must finish after a lost cancellation notification");
    require(source.stop_requested() && condition.waits > 0,
            "test must cancel inside the fallback wait predicate");
}

// Check dispatch independently of which overloads the host STL implements.
struct NativeCondition {
    bool called = false;
    template <typename Lock, typename Predicate>
    bool wait(Lock&, std::stop_token, Predicate predicate) {
        called = true;
        return predicate();
    }
};
} // namespace

int main() {
    cancellation_and_completion_contract<std::condition_variable_any>();
    cancellation_and_completion_contract<PollingCondition>();
    normal_completion<std::condition_variable_any>();
    normal_completion<PollingCondition>();
    cancellation_between_predicate_and_wait();
    NativeCondition native;
    std::mutex mutex;
    std::unique_lock lock(mutex);
    require(snow::image::detail::stop_aware_wait(native, lock, {}, [] { return true; }) &&
                native.called,
            "available native overload must be used");
    std::cout << "stop-aware wait checks passed\n";
}
