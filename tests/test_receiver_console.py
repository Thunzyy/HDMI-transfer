"""Tests for the interactive receiver console (hdmi-receiver).

Validates menu dispatch, device detection, parameter collection, delegation
to existing functions, and clean Ctrl-C handling.  All InquirerPy prompts
and cv2 calls are mocked -- no real terminal interaction or hardware needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ------------------------------------------------------------------
# Test 1: Dispatch table covers all menu actions
# ------------------------------------------------------------------


def test_dispatch_table_covers_all_actions():
    """Verify every non-Quit menu item has a dispatch handler."""
    from hdmi_exfil.receiver.cli.console import (
        _DISPATCH,
        _MENU_CALIBRATE,
        _MENU_DETECT,
        _MENU_QUIT,
        _MENU_RECEIVE,
        _MENU_SETTINGS,
        _MENU_STATS,
    )

    for action in [
        _MENU_RECEIVE,
        _MENU_CALIBRATE,
        _MENU_DETECT,
        _MENU_STATS,
        _MENU_SETTINGS,
    ]:
        assert action in _DISPATCH, f"Missing dispatch for {action}"
    assert _MENU_QUIT not in _DISPATCH  # Quit is handled by loop break


# ------------------------------------------------------------------
# Test 2: Detect capture card action (devices found)
# ------------------------------------------------------------------


@patch("hdmi_exfil.receiver.cli.console._detect_devices")
def test_action_detect_with_devices(mock_detect, capsys):
    """_action_detect prints detected devices."""
    from hdmi_exfil.receiver.cli.console import _action_detect

    mock_detect.return_value = [
        {"index": 0, "name": "Webcam", "width": 1920, "height": 1080, "fps": 60.0},
        {"index": 1, "name": "Elgato 4K X", "width": 3840, "height": 2160, "fps": 30.0},
    ]
    _action_detect()
    output = capsys.readouterr().out
    assert "2 device(s)" in output
    assert "Webcam" in output
    assert "Elgato 4K X" in output


# ------------------------------------------------------------------
# Test 3: Detect capture card action (no devices)
# ------------------------------------------------------------------


@patch("hdmi_exfil.receiver.cli.console._detect_devices")
def test_action_detect_no_devices(mock_detect, capsys):
    """_action_detect handles no devices gracefully."""
    from hdmi_exfil.receiver.cli.console import _action_detect

    mock_detect.return_value = []
    _action_detect()
    output = capsys.readouterr().out
    assert "No capture devices found" in output


# ------------------------------------------------------------------
# Test 4: Receive action collects params and delegates
# ------------------------------------------------------------------


@patch("hdmi_exfil.receiver.cli.console.settings")
@patch("hdmi_exfil.receiver.cli.console.run_receive")
@patch("hdmi_exfil.receiver.cli.console._detect_devices")
@patch("hdmi_exfil.receiver.cli.console.inquirer")
def test_action_receive(mock_inq, mock_detect, mock_run_receive, mock_settings):
    """_action_receive collects parameters and calls run_receive()."""
    from hdmi_exfil.receiver.cli.console import _action_receive

    # No saved device — force prompt
    mock_settings.load.return_value = {
        "receiver": {"device_name": None, "profile": "speed", "mode": "auto", "output": "received_files"}
    }
    mock_settings.get.return_value = None

    # Mock two devices
    mock_detect.return_value = [
        {"index": 0, "name": "Webcam", "width": 1920, "height": 1080, "fps": 60.0},
        {"index": 1, "name": "Elgato 4K X", "width": 3840, "height": 2160, "fps": 30.0},
    ]

    # Mock prompt responses: device, profile, mode
    mock_select = MagicMock()
    mock_select.execute.side_effect = [0, "speed", "auto"]
    mock_inq.select.return_value = mock_select

    mock_text = MagicMock()
    mock_text.execute.return_value = "output_dir"
    mock_inq.text.return_value = mock_text

    _action_receive()

    mock_run_receive.assert_called_once()
    call_kwargs = mock_run_receive.call_args
    if call_kwargs.kwargs:
        assert call_kwargs.kwargs["source"] == 0
        assert call_kwargs.kwargs["mode"] == "auto"
        assert call_kwargs.kwargs["output"] == "output_dir"
    else:
        assert call_kwargs[1]["source"] == 0


# ------------------------------------------------------------------
# Test 5: Receive action with single device skips selection
# ------------------------------------------------------------------


@patch("hdmi_exfil.receiver.cli.console.settings")
@patch("hdmi_exfil.receiver.cli.console.run_receive")
@patch("hdmi_exfil.receiver.cli.console._detect_devices")
@patch("hdmi_exfil.receiver.cli.console.inquirer")
def test_action_receive_single_device(mock_inq, mock_detect, mock_run_receive, mock_settings):
    """Single device case skips device selection prompt."""
    from hdmi_exfil.receiver.cli.console import _action_receive

    mock_settings.load.return_value = {
        "receiver": {"device_name": None, "profile": "speed", "mode": "auto", "output": "received_files"}
    }
    mock_settings.get.return_value = None

    # Mock single device
    mock_detect.return_value = [
        {"index": 0, "name": "Webcam", "width": 1920, "height": 1080, "fps": 60.0},
    ]

    # Mock prompt responses: profile, output dir, mode (no device selection)
    mock_select = MagicMock()
    mock_select.execute.side_effect = ["speed", "auto"]
    mock_inq.select.return_value = mock_select

    mock_text = MagicMock()
    mock_text.execute.return_value = "received_files"
    mock_inq.text.return_value = mock_text

    _action_receive()

    mock_run_receive.assert_called_once()
    call_kwargs = mock_run_receive.call_args
    if call_kwargs.kwargs:
        assert call_kwargs.kwargs["source"] == 0


# ------------------------------------------------------------------
# Test 6: Stats action with no prior transfer
# ------------------------------------------------------------------


def test_action_stats_no_transfer(capsys):
    """_action_stats shows message when no transfer completed."""
    from hdmi_exfil.receiver.cli.console import _action_stats

    _action_stats()
    output = capsys.readouterr().out
    assert "No transfer completed yet" in output


# ------------------------------------------------------------------
# Test 7: Settings action prints info
# ------------------------------------------------------------------


@patch("hdmi_exfil.receiver.cli.console.inquirer")
def test_action_settings(mock_inq, capsys):
    """_action_settings prints current settings and handles Back to menu."""
    from hdmi_exfil.receiver.cli.console import _action_settings

    mock_select = MagicMock()
    mock_select.execute.return_value = "Back to menu"
    mock_inq.select.return_value = mock_select

    _action_settings()
    output = capsys.readouterr().out
    assert "Receiver Settings" in output
    assert "speed" in output or "balanced" in output


# ------------------------------------------------------------------
# Test 8: Ctrl-C exits cleanly
# ------------------------------------------------------------------


@patch("hdmi_exfil.receiver.cli.console._show_main_menu")
def test_main_ctrl_c_exits_cleanly(mock_menu):
    """main() exits cleanly on KeyboardInterrupt without traceback."""
    from hdmi_exfil.receiver.cli.console import main

    mock_menu.side_effect = KeyboardInterrupt()
    # Should NOT raise -- exits cleanly
    main()


# ------------------------------------------------------------------
# Test 9: Quit selection breaks loop
# ------------------------------------------------------------------


@patch("hdmi_exfil.receiver.cli.console._show_main_menu")
def test_main_quit_breaks_loop(mock_menu):
    """Selecting Quit breaks the main loop."""
    from hdmi_exfil.receiver.cli.console import _MENU_QUIT, main

    mock_menu.return_value = _MENU_QUIT
    main()  # Should return normally
    mock_menu.assert_called_once()


# ------------------------------------------------------------------
# Test 10: Dispatch dispatches to correct handler
# ------------------------------------------------------------------


@patch("hdmi_exfil.receiver.cli.console._show_main_menu")
def test_main_dispatches_action(mock_menu):
    """main() dispatches a menu selection to the correct handler."""
    from hdmi_exfil.receiver.cli.console import (
        _DISPATCH,
        _MENU_DETECT,
        _MENU_QUIT,
        main,
    )

    # First call returns Detect, second call returns Quit
    mock_menu.side_effect = [_MENU_DETECT, _MENU_QUIT]

    mock_detect = MagicMock()
    with patch.dict(_DISPATCH, {_MENU_DETECT: mock_detect}):
        main()
        mock_detect.assert_called_once()
