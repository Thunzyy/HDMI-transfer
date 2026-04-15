from __future__ import annotations


def test_legacy_imports_resolve_to_new_canonical_modules() -> None:
    from hdmi_transfer.compat.imports import COMPAT_TARGET_ATTR, reexport

    import hdmi_transfer.capture.sampler as legacy_capture_sampler
    import hdmi_transfer.capture as legacy_capture_package
    import hdmi_transfer.cli.calibrate as legacy_calibrate_cli
    import hdmi_transfer.cli.receive as legacy_receive_cli
    import hdmi_transfer.cli.sender_console as legacy_sender_console
    import hdmi_transfer.config as legacy_config
    import hdmi_transfer.display as legacy_display_package
    import hdmi_transfer.display.renderer as legacy_renderer
    import hdmi_transfer.file_handling as legacy_file_handling_package
    import hdmi_transfer.file_handling.metadata as legacy_metadata
    import hdmi_transfer.prng as legacy_prng
    import hdmi_transfer.protocols as legacy_protocols
    import hdmi_transfer.protocols.fountain as legacy_fountain
    from hdmi_transfer.core.capture.sampler import sample_frame
    from hdmi_transfer.core.config import PROFILES
    from hdmi_transfer.core.file_handling.metadata import build_start_metadata
    from hdmi_transfer.core.prng import PRNG
    from hdmi_transfer.core.protocols.fountain import FountainProtocol
    from hdmi_transfer.interfaces.cli.calibrate import main as calibrate_main
    from hdmi_transfer.interfaces.cli.receive import main as receive_main
    from hdmi_transfer.interfaces.cli.sender_console import main as sender_console_main
    from hdmi_transfer.sender.display.renderer import FrameRenderer

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
    assert getattr(legacy_fountain, COMPAT_TARGET_ATTR) == "hdmi_transfer.core.protocols.fountain"
    assert getattr(legacy_config, COMPAT_TARGET_ATTR) == "hdmi_transfer.core.config"
    assert getattr(legacy_capture_package, COMPAT_TARGET_ATTR) == "hdmi_transfer.core.capture"
    assert getattr(legacy_display_package, COMPAT_TARGET_ATTR) == "hdmi_transfer.sender.display"
    assert getattr(legacy_file_handling_package, COMPAT_TARGET_ATTR) == "hdmi_transfer.core.file_handling"
