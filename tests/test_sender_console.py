"""Tests for the interactive sender console (hdmi-sender).

Validates menu dispatch, parameter collection, delegation to existing
functions, and clean Ctrl-C handling.  All InquirerPy prompts are mocked
-- no real terminal interaction needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ------------------------------------------------------------------
# Test 1: Interface entry points exist
# ------------------------------------------------------------------


def test_cli_entry_points_import_from_interfaces_layer():
    """New interface-layer CLI entry points are importable and callable."""
    from hdmi_transfer.interfaces.cli.calibrate import main as calibrate_main
    from hdmi_transfer.interfaces.cli.receive import main as receive_main
    from hdmi_transfer.interfaces.cli.receiver_console import (
        main as receiver_console_main,
    )
    from hdmi_transfer.interfaces.cli.send import main as send_main
    from hdmi_transfer.interfaces.cli.sender_console import (
        main as sender_console_main,
    )

    assert callable(send_main)
    assert callable(receive_main)
    assert callable(calibrate_main)
    assert callable(sender_console_main)
    assert callable(receiver_console_main)


# ------------------------------------------------------------------
# Test 2: Dispatch table covers all menu actions
# ------------------------------------------------------------------


def test_dispatch_table_covers_all_actions():
    """Verify every non-Quit menu item has a dispatch handler."""
    from hdmi_transfer.interfaces.cli.sender_console import (
        _DISPATCH,
        _MENU_BENCHMARK,
        _MENU_CALIBRATE,
        _MENU_DETECT,
        _MENU_QUIT,
        _MENU_SEND_BROWSER,
        _MENU_SEND_PYTHON,
    )

    for action in [
        _MENU_SEND_PYTHON,
        _MENU_SEND_BROWSER,
        _MENU_CALIBRATE,
        _MENU_DETECT,
        _MENU_BENCHMARK,
    ]:
        assert action in _DISPATCH, f"Missing dispatch for {action}"
    assert _MENU_QUIT not in _DISPATCH  # Quit is handled by loop break


# ------------------------------------------------------------------
# Test 3: Detect hardware action
# ------------------------------------------------------------------


@patch("hdmi_transfer.interfaces.cli.sender_console.get_monitors")
def test_action_detect(mock_monitors, capsys):
    """_action_detect prints detected monitors."""
    from hdmi_transfer.interfaces.cli.sender_console import _action_detect

    mock_monitors.return_value = [
        {"width": 1920, "height": 1080, "left": 0, "top": 0},
        {"width": 3840, "height": 2160, "left": 1920, "top": 0},
    ]
    _action_detect()
    output = capsys.readouterr().out
    assert "2 monitor(s)" in output
    assert "1920x1080" in output
    assert "3840x2160" in output


# ------------------------------------------------------------------
# Test 4: Send Python collects params and delegates
# ------------------------------------------------------------------


@patch("hdmi_transfer.interfaces.cli.sender_console.run_send")
@patch("hdmi_transfer.interfaces.cli.sender_console.get_monitors")
@patch("hdmi_transfer.interfaces.cli.sender_console.inquirer")
def test_action_send_python(mock_inq, mock_monitors, mock_run_send):
    """_action_send_python collects parameters and calls run_send()."""
    from hdmi_transfer.interfaces.cli.sender_console import _action_send_python

    # Mock single monitor (skips monitor selection prompt)
    mock_monitors.return_value = [
        {"width": 1920, "height": 1080, "left": 0, "top": 0}
    ]

    # Mock prompt responses
    mock_filepath = MagicMock()
    mock_filepath.execute.return_value = "/tmp/test.bin"
    mock_inq.filepath.return_value = mock_filepath

    mock_select = MagicMock()
    # First call: profile, Second call: mode
    mock_select.execute.side_effect = ["speed", "sequential"]
    mock_inq.select.return_value = mock_select

    _action_send_python()

    mock_run_send.assert_called_once()
    call_kwargs = mock_run_send.call_args
    # Check input_path was passed correctly (positional or keyword)
    if call_kwargs.kwargs:
        assert call_kwargs.kwargs["input_path"] == "/tmp/test.bin"
    else:
        assert call_kwargs[1]["input_path"] == "/tmp/test.bin"


# ------------------------------------------------------------------
# Test 5: Benchmark action delegates
# ------------------------------------------------------------------


@patch("hdmi_transfer.interfaces.cli.sender_console.inquirer")
def test_action_benchmark(mock_inq):
    """_action_benchmark calls run_benchmark with correct params."""
    from hdmi_transfer.interfaces.cli.sender_console import _action_benchmark

    mock_select = MagicMock()
    mock_select.execute.side_effect = ["speed", "fountain"]
    mock_inq.select.return_value = mock_select

    with patch("hdmi_transfer.core.cli.benchmark.run_benchmark") as mock_bench:
        mock_bench.return_value = MagicMock(
            frames_per_sec=100.0,
            bytes_per_sec=50000.0,
            overhead_pct=5.0,
            error_rate=0.0,
            duration_sec=10.0,
        )
        _action_benchmark()
        mock_bench.assert_called_once()


# ------------------------------------------------------------------
# Test 6: Ctrl-C exits cleanly
# ------------------------------------------------------------------


@patch("hdmi_transfer.interfaces.cli.sender_console._show_main_menu")
def test_main_ctrl_c_exits_cleanly(mock_menu):
    """main() exits cleanly on KeyboardInterrupt without traceback."""
    from hdmi_transfer.interfaces.cli.sender_console import main

    mock_menu.side_effect = KeyboardInterrupt()
    # Should NOT raise -- exits cleanly
    main()


# ------------------------------------------------------------------
# Test 7: Quit selection breaks loop
# ------------------------------------------------------------------


@patch("hdmi_transfer.interfaces.cli.sender_console._show_main_menu")
def test_main_quit_breaks_loop(mock_menu):
    """Selecting Quit breaks the main loop."""
    from hdmi_transfer.interfaces.cli.sender_console import _MENU_QUIT, main

    mock_menu.return_value = _MENU_QUIT
    main()  # Should return normally
    mock_menu.assert_called_once()


# ------------------------------------------------------------------
# Test 8: Dispatch dispatches to correct handler
# ------------------------------------------------------------------


@patch("hdmi_transfer.interfaces.cli.sender_console._show_main_menu")
def test_main_dispatches_action(mock_menu):
    """main() dispatches a menu selection to the correct handler."""
    from hdmi_transfer.interfaces.cli.sender_console import (
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
