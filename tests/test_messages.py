import ast
from pathlib import Path

from winusb_forge.messages import ERROR_TEXT, terminal_text


def test_all_literal_error_codes_have_both_languages():
    source = Path(__file__).resolve().parents[1] / "src/winusb_forge"
    codes = set()
    for path in source.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ForgeError"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                codes.add(node.args[0].value)
    assert codes <= ERROR_TEXT.keys()
    for code in codes:
        english, spanish = ERROR_TEXT[code]
        assert english and spanish and english != spanish


def test_untrusted_details_cannot_control_terminal():
    result = terminal_text("bad\x1b[2J\r\n\u202efilename ñ")
    assert "\x1b" not in result and "\n" not in result and "\r" not in result
    assert "\u202e" not in result
    assert "ñ" in result
    assert "\\x1b" in result


def test_details_are_bounded():
    assert terminal_text("a" * 600) == "a" * 500 + "…"
