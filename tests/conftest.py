import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--hardware",
        action="store_true",
        default=False,
        help="Run tests that require Elgato capture card hardware",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "hardware: mark test as requiring Elgato capture card"
    )


def pytest_runtest_setup(item):
    if "hardware" in item.keywords and not item.config.getoption("--hardware"):
        pytest.skip("Skipping hardware test: use --hardware to run")
