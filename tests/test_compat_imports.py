from __future__ import annotations


def test_legacy_imports_resolve_to_new_canonical_modules() -> None:
    from hdmi_exfil.compat.imports import COMPAT_TARGET_ATTR, reexport

    import hdmi_exfil.capture.sampler as legacy_capture_sampler
    import hdmi_exfil.capture as legacy_capture_package
    import hdmi_exfil.cli.calibrate as legacy_calibrate_cli
    import hdmi_exfil.cli.receive as legacy_receive_cli
    import hdmi_exfil.cli.sender_console as legacy_sender_console
    import hdmi_exfil.config as legacy_config
    import hdmi_exfil.display as legacy_display_package
    import hdmi_exfil.display.renderer as legacy_renderer
    import hdmi_exfil.file_handling as legacy_file_handling_package
    import hdmi_exfil.file_handling.metadata as legacy_metadata
    import hdmi_exfil.prng as legacy_prng
    import hdmi_exfil.protocols as legacy_protocols
    import hdmi_exfil.protocols.fountain as legacy_fountain
    from hdmi_exfil.core.capture.sampler import sample_frame
    from hdmi_exfil.core.config import PROFILES
    from hdmi_exfil.core.file_handling.metadata import build_start_metadata
    from hdmi_exfil.core.prng import PRNG
    from hdmi_exfil.core.protocols.fountain import FountainProtocol
    from hdmi_exfil.interfaces.cli.calibrate import main as calibrate_main
    from hdmi_exfil.interfaces.cli.receive import main as receive_main
    from hdmi_exfil.interfaces.cli.sender_console import main as sender_console_main
    from hdmi_exfil.sender.display.renderer import FrameRenderer

    assert callable(reexport)
    assert legacy_fountain.FountainProtocol is FountainProtocol
    assert legacy_protocols.FountainProtocol is FountainProtocol
    assert legacy_prng.PRNG is PRNG
    assert legacy_config.PROFILES is PROFILES
    assert legacy_capture_sampler.sample_frame is sample_frame
    assert legacy_metadata.build_start_metadata is build_start_metadata
    assert legacy_renderer.FrameRenderer is FrameRenderer
    assert legacy_receive_cli.main is receive_main
    assert legacy_calibrate_cli.main is calibrate_main
    assert legacy_sender_console.main is sender_console_main
    assert getattr(legacy_fountain, COMPAT_TARGET_ATTR) == "hdmi_exfil.core.protocols.fountain"
    assert getattr(legacy_config, COMPAT_TARGET_ATTR) == "hdmi_exfil.core.config"
    assert getattr(legacy_capture_package, COMPAT_TARGET_ATTR) == "hdmi_exfil.core.capture"
    assert getattr(legacy_display_package, COMPAT_TARGET_ATTR) == "hdmi_exfil.sender.display"
    assert getattr(legacy_file_handling_package, COMPAT_TARGET_ATTR) == "hdmi_exfil.core.file_handling"
