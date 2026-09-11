from lalk_server.__main__ import parse_args


def test_help_does_not_load_server_dependencies() -> None:
    import subprocess
    import sys

    check = """
import sys
from lalk_server.__main__ import main
sys.argv = ["lalk-server", "--help"]
try:
    main()
except SystemExit as error:
    assert error.code == 0
else:
    raise AssertionError("help must exit")
assert "lalk_server.app" not in sys.modules
assert "lalk" not in sys.modules
assert "uvicorn" not in sys.modules
"""
    subprocess.run([sys.executable, "-c", check], check=True, timeout=10)


def test_cli_allows_omitting_config() -> None:
    args = parse_args([])

    assert args.config is None
    assert args.port == 17841


def test_cli_parses_config_and_port() -> None:
    args = parse_args(["--config", "/tmp/config.json", "--port", "19000"])

    assert str(args.config) == "/tmp/config.json"
    assert args.port == 19000
