// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QGuiApplication>
#include <QScreen>
#include <QRectF>
#import <AppKit/AppKit.h>

#include <cstdint>
#include <optional>

// Qt 6.10 does not expose the native-screen APIs used by newer upstream Qt.
// Keep the existing AppKit fallback here, outside screenshot geometry algorithms.
namespace snow_shot::platform::qt_screen_compat {

inline QRectF macDesktopRect(NSRect rect) {
    NSScreen* primary = NSScreen.screens.firstObject;
    if (primary == nil) {
        return {};
    }
    const CGFloat desktopTop = NSMaxY(primary.frame);
    return {rect.origin.x, desktopTop - NSMaxY(rect), rect.size.width, rect.size.height};
}

inline std::optional<uint32_t> macNativeDisplayId(const QScreen& screen) {
    const QRectF target(screen.geometry());
    for (NSScreen* native in NSScreen.screens) {
        if (macDesktopRect(native.frame) != target) {
            continue;
        }
        NSNumber* number = [native.deviceDescription objectForKey:@"NSScreenNumber"];
        if (number != nil) {
            return number.unsignedIntValue;
        }
    }
    return std::nullopt;
}

inline QScreen* macScreenForDisplayId(uint32_t displayId) {
    for (QScreen* screen : QGuiApplication::screens()) {
        if (screen == nullptr) {
            continue;
        }
        const auto nativeId = macNativeDisplayId(*screen);
        if (nativeId && *nativeId == displayId) {
            return screen;
        }
    }
    return nullptr;
}

} // namespace snow_shot::platform::qt_screen_compat
