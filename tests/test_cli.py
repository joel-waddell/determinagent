import io
import json

from determinagent.__main__ import main


def run(capsys, argv, stdin):
    import sys

    sys.stdin = io.StringIO(stdin)
    try:
        code = main(argv)
    finally:
        sys.stdin = sys.__stdin__
    return code, json.loads(capsys.readouterr().out)


def test_rulespeak_cli(capsys):
    code, out = run(capsys, ["check", "rulespeak"], "Each order must have at least one line item.\n")
    assert code == 0 and out["outcome"]["form"] == "conforms" and out["template"]["id"] == "RS-T01"


def test_rulespeak_cli_multiple_lines(capsys):
    code, out = run(capsys, ["check", "rulespeak"], "Each order must have a customer.\nOrders ship fast.\n")
    assert code == 1 and [o["outcome"]["profile_acceptance"] for o in out] == ["accepted", "rejected"]


def test_gherkin_cli(capsys):
    code, out = run(capsys, ["check", "gherkin"], "Feature: f\n  Scenario: s\n    Given a\n    When b\n    Then c\n")
    assert code == 0 and out["conformant"]
