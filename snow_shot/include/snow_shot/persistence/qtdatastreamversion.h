#pragma once

namespace snow_shot::persistence {

// Pinned and screenshot-style records persist QDataStream payloads without a
// stream-version header. Qt 6.11 uses format version 24; keep that wire format
// when compiling the macOS 13 compatibility build with Qt 6.10.
inline constexpr int kQt611DataStreamVersion = 24;

} // namespace snow_shot::persistence
