# Requirements: HDMI Exfil v1.1

**Defined:** 2026-03-02
**Core Value:** Maximum throughput data transfer over HDMI without leaving any trace on the source machine.

## v1.1 Requirements

Requirements for milestone v1.1: Interactive CLI Consoles & Monorepo Restructure.

### Monorepo Structure

- [x] **STRUCT-01**: Code is organized into core/, sender/, receiver/ subpackages within src/hdmi_exfil/
- [x] **STRUCT-02**: User can install sender-only via `pip install hdmi-exfil[sender]` (pygame-ce, screeninfo)
- [x] **STRUCT-03**: User can install receiver-only via `pip install hdmi-exfil[receiver]` (opencv-python)
- [x] **STRUCT-04**: User can install everything via `pip install hdmi-exfil` or `hdmi-exfil[all]`
- [x] **STRUCT-05**: Existing CLI commands (hdmi-send, hdmi-recv, hdmi-calibrate, hdmi-bench) work unchanged after restructure
- [x] **STRUCT-06**: cv2.resize in protocol encoding is replaced with np.repeat for clean core/sender dependency split
- [x] **STRUCT-07**: All existing tests pass after restructure (no regressions)

### Sender Console

- [x] **SEND-01**: User can launch `hdmi-sender` to get an interactive arrow-key menu
- [ ] **SEND-02**: Sender menu offers: Send file (Python), Send file (Browser), Calibrate, Detect hardware, Benchmark, Quit
- [ ] **SEND-03**: User can select file to send via interactive file path prompt with autocomplete
- [ ] **SEND-04**: User can select resolution profile (speed/balanced/quality) via arrow-key prompt
- [x] **SEND-05**: User can select encoding mode (sequential/fountain) via arrow-key prompt
- [ ] **SEND-06**: User can select target monitor via arrow-key prompt with detected monitors listed
- [ ] **SEND-07**: After any action completes, user returns to the main menu
- [ ] **SEND-08**: Ctrl-C cleanly exits at any prompt without traceback

### Receiver Console

- [ ] **RECV-01**: User can launch `hdmi-receiver` to get an interactive arrow-key menu
- [ ] **RECV-02**: Receiver menu offers: Receive file, Calibrate signal, Detect capture card, Last transfer stats, Settings, Quit
- [ ] **RECV-03**: User can select capture device via arrow-key prompt with detected devices listed
- [ ] **RECV-04**: User can select resolution profile (speed/balanced/quality) via arrow-key prompt
- [ ] **RECV-05**: User can configure output directory via interactive prompt
- [ ] **RECV-06**: After any action completes, user returns to the main menu
- [ ] **RECV-07**: Ctrl-C cleanly exits at any prompt without traceback

## Future Requirements

Deferred to v1.2+. Tracked but not in current roadmap.

### UX Differentiators

- **UX-D1**: Settings persistence across sessions (~/.hdmi-exfil/config.json)
- **UX-D2**: Confirm prompt before starting send/receive with parameter summary
- **UX-D3**: Colored output and status indicators (ANSI colors)
- **UX-D4**: Web browser auto-launch for "Send File (Browser)" option
- **UX-D5**: Advanced settings submenu (FPS override, redundancy, buffer size)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Full TUI (Textual/curses) | Over-engineered for menu prompts; conflicts with pygame/cv2 event loops |
| Replace argparse CLIs | Existing commands must survive for scripting/automation |
| Async menu updates during transfers | Menu is inactive during send/receive; progress uses existing ProgressTracker |
| Separate PyPI packages | Monorepo extras achieve the same install flexibility with less maintenance |
| GUI application | CLI + browser sender is sufficient per v1.0 scope |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| STRUCT-01 | Phase 7 | Complete |
| STRUCT-02 | Phase 7 | Complete |
| STRUCT-03 | Phase 7 | Complete |
| STRUCT-04 | Phase 7 | Complete |
| STRUCT-05 | Phase 7 | Complete |
| STRUCT-06 | Phase 7 | Complete |
| STRUCT-07 | Phase 7 | Complete |
| SEND-01 | Phase 8 | Complete |
| SEND-02 | Phase 8 | Pending |
| SEND-03 | Phase 8 | Pending |
| SEND-04 | Phase 8 | Pending |
| SEND-05 | Phase 8 | Complete |
| SEND-06 | Phase 8 | Pending |
| SEND-07 | Phase 8 | Pending |
| SEND-08 | Phase 8 | Pending |
| RECV-01 | Phase 9 | Pending |
| RECV-02 | Phase 9 | Pending |
| RECV-03 | Phase 9 | Pending |
| RECV-04 | Phase 9 | Pending |
| RECV-05 | Phase 9 | Pending |
| RECV-06 | Phase 9 | Pending |
| RECV-07 | Phase 9 | Pending |

**Coverage:**
- v1.1 requirements: 22 total
- Mapped to phases: 22
- Unmapped: 0

---
*Requirements defined: 2026-03-02*
*Last updated: 2026-03-02 -- traceability updated with phase mappings*
