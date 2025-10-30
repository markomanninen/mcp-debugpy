import sys
import types

from cli import main as cli_main


def test_cli_help_returns_zero(capsys):
    # Call the CLI main with --help and ensure it returns 0 and prints help text
    ret = cli_main(["--help"])
    captured = capsys.readouterr()
    # The server.print_help prints multiple lines; we expect some output
    assert isinstance(ret, int) and ret == 0
    assert captured.out
