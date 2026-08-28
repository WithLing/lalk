from lalk_server.__main__ import parse_args


def test_cli_allows_omitting_config() -> None:
    args = parse_args([])

    assert args.config is None
    assert args.port == 17841


def test_cli_parses_config_and_port() -> None:
    args = parse_args(["--config", "/tmp/config.json", "--port", "19000"])

    assert str(args.config) == "/tmp/config.json"
    assert args.port == 19000
