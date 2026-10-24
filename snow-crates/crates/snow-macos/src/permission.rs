use crate::{MacError, MacResult};
use objc2_core_graphics::{CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess};
use objc2_foundation::{NSOperatingSystemVersion, NSProcessInfo};

pub(crate) fn os_at_least(major: isize, minor: isize) -> bool {
    NSProcessInfo::processInfo().isOperatingSystemAtLeastVersion(NSOperatingSystemVersion {
        majorVersion: major,
        minorVersion: minor,
        patchVersion: 0,
    })
}

pub fn supported_os() -> bool {
    os_at_least(13, 0)
}
pub fn screen_capture_authorized() -> bool {
    CGPreflightScreenCaptureAccess()
}
/// Explicit host-initiated request; ordinary acquisition never prompts implicitly.
pub fn request_screen_capture_access() -> bool {
    CGRequestScreenCaptureAccess()
}
pub(crate) fn check_access() -> MacResult<()> {
    if objc2::MainThreadMarker::new().is_some() {
        return Err(MacError::InvalidConfig("blocking capture APIs must run on a worker while the host main run loop remains active".into()));
    }
    if !supported_os() {
        return Err(MacError::UnsupportedOs);
    }
    if !screen_capture_authorized() {
        return Err(MacError::PermissionDenied);
    }
    Ok(())
}
