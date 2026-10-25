#pragma once

#import <AppKit/AppKit.h>
#import <objc/message.h>

namespace snow_shot::platform::appkit_compat {

inline void activateApplication() {
    static const SEL selector = NSSelectorFromString(@"activate");
    if ([NSApp respondsToSelector:selector]) {
        const auto send = reinterpret_cast<void (*)(id, SEL)>(objc_msgSend);
        send(NSApp, selector);
        return;
    }
    [NSApp activateIgnoringOtherApps:YES];
}

inline void yieldActivationToApplication(NSRunningApplication* application) {
    if (application == nil) {
        return;
    }
    static const SEL selector = NSSelectorFromString(@"yieldActivationToApplication:");
    if ([NSApp respondsToSelector:selector]) {
        const auto send = reinterpret_cast<void (*)(id, SEL, id)>(objc_msgSend);
        send(NSApp, selector, application);
    }
}

} // namespace snow_shot::platform::appkit_compat
