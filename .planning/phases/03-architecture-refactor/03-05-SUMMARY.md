---
phase: 03-architecture-refactor
plan: 05
subsystem: io
tags: [opencv, screeninfo, capture, display, file-handling, cross-platform]

# Dependency graph
requires:
  - phase: 03-02
    provides: "Sampler and encoding leaf modules used alongside capture"
  - phase: 03-03
    provides: "Sequential protocol that consumes capture/display/file I/O"
provides:
  - "CaptureSource: cross-platform VideoCapture wrapper"
  - "FrameRenderer: fullscreen OpenCV display manager"
  - "get_monitors(): cross-platform monitor detection"
  - "read_input(): file/directory reader with zip packaging"
  - "write_output(): safe file writer with path sanitization"
  - "verify_integrity(): SHA-256 digest comparison"
affects: [03-06, 03-07, 04-performance, 05-fountain-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Context manager protocol on I/O wrappers (CaptureSource, FrameRenderer)"
    - "Platform detection via sys.platform for backend selection"
    - "Lazy import of screeninfo to handle missing dependency gracefully"
    - "Path sanitization via os.path.basename to prevent traversal"

key-files:
  created:
    - src/hdmi_exfil/capture/source.py
    - src/hdmi_exfil/display/renderer.py
    - src/hdmi_exfil/display/monitors.py
    - src/hdmi_exfil/file_handling/reader.py
    - src/hdmi_exfil/file_handling/writer.py
  modified: []

key-decisions:
  - "CaptureSource tries preferred backend first, falls back to CAP_ANY"
  - "get_monitors() uses lazy import + broad except to never crash on headless/CI"
  - "FrameRenderer wraps namedWindow+moveWindow+setWindowProperty lifecycle"
  - "write_output sanitizes filename with os.path.basename (prevents ../../ traversal)"

patterns-established:
  - "Context manager: all I/O resources implement __enter__/__exit__"
  - "Fallback pattern: try preferred, catch, use safe default"
  - "Pure stdlib: reader and writer use only os/shutil/hashlib (no heavy deps)"

# Metrics
duration: 3min
completed: 2026-02-16
---

# Phase 03 Plan 05: I/O Layer Summary

**Cross-platform capture/display/file I/O wrappers with V4L2/DSHOW/AVFoundation auto-detection, screeninfo monitor listing, and safe file read/write**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-16T14:05:27Z
- **Completed:** 2026-02-16T14:08:16Z
- **Tasks:** 2
- **Files created:** 5

## Accomplishments
- CaptureSource auto-detects backend per platform (V4L2 on Linux, DSHOW on Windows, AVFoundation on macOS) with CAP_ANY fallback
- FrameRenderer manages fullscreen OpenCV window lifecycle with context manager
- get_monitors() replaces Windows-only ctypes.windll with cross-platform screeninfo, falling back to 1920x1080 default
- FileReader handles both files and directories (zip packaging via shutil.make_archive)
- FileWriter sanitizes filenames (os.path.basename) and creates output dirs automatically
- verify_integrity provides SHA-256 digest comparison for received data

## Task Commits

Each task was committed atomically:

1. **Task 1: Create capture source and display modules** - `492a052` (feat)
2. **Task 2: Create file handling reader and writer** - `60707cf` (feat)

## Files Created/Modified
- `src/hdmi_exfil/capture/source.py` - Cross-platform VideoCapture wrapper with backend auto-detection
- `src/hdmi_exfil/display/renderer.py` - Fullscreen OpenCV window for frame display
- `src/hdmi_exfil/display/monitors.py` - Cross-platform monitor detection via screeninfo
- `src/hdmi_exfil/file_handling/reader.py` - File/directory reader with zip packaging
- `src/hdmi_exfil/file_handling/writer.py` - Safe file writer with path sanitization and SHA-256 verification

## Decisions Made
- CaptureSource tries platform-specific backend first, then falls back to CAP_ANY -- mirrors original receiver.py behavior but adds graceful degradation
- get_monitors() catches ImportError, RuntimeError, and generic Exception to never crash on headless/CI environments -- returns safe default
- FrameRenderer destroys all windows (not just its own) via cv2.destroyAllWindows -- consistent with original sender.py behavior
- write_output uses os.path.basename for sanitization rather than regex -- simpler, handles all OS path separators

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All I/O modules in place for CLI layer (03-06) to compose into send/receive commands
- Integration testing (03-07) can verify capture+protocol+file I/O end-to-end
- No Windows-specific imports at module level -- cross-platform safe

---
*Phase: 03-architecture-refactor*
*Completed: 2026-02-16*
