import textwrap

import pytest

from determinagent.conformance import gherkin


def g(src: str):
    return gherkin.check(textwrap.dedent(src).lstrip())


GOOD = """
Feature: Refund requests
  As a customer I want to request a refund so that I get my money back.

  Background:
    Given a registered customer

  Scenario: Refund within the return window
    Given an order delivered 10 days ago
    When the customer requests a refund
    Then the refund is approved
    And the customer is notified

  Scenario Outline: Refund outside the return window
    Given an order delivered <days> days ago
    When the customer requests a refund
    Then the refund is <outcome>

    Examples:
      | days | outcome  |
      | 31   | rejected |
      | 90   | rejected |

  Rule: Gift cards are never refunded
    Scenario: Gift card refund
      Given an order paid by gift card
      When the customer requests a refund
      Then the refund is rejected
"""


def test_conformant_feature():
    r = g(GOOD)
    assert r.conformant and r.defects == [], r.to_dict()


@pytest.mark.parametrize(
    "src,codes",
    [
        ("nothing here\n", ["GK-PARSE-001"]),
        ("", ["GK-STR-001"]),
        ("Feature:\n  Scenario: s\n    Given a\n    When b\n    Then c\n", ["GK-STR-002"]),
        ("Feature: f\n  Just a description\n", ["GK-STR-003"]),
        ("Feature: f\n  Scenario:\n    Given a\n    When b\n    Then c\n", ["GK-STR-004"]),
        ("Feature: f\n  Scenario: s\n", ["GK-STR-005"]),
        ("Feature: f\n  Scenario: s\n    Given a\n    Then c\n", ["GK-SEQ-001"]),
        ("Feature: f\n  Scenario: s\n    Given a\n    When b\n", ["GK-SEQ-002"]),
        ("Feature: f\n  Scenario: s\n    When b\n    Then c\n    When d\n    Then e\n", ["GK-SEQ-003", "GK-SEQ-004"]),
        ("Feature: f\n  Scenario: s\n    And a\n    When b\n    Then c\n", ["GK-SEQ-005", "GK-SEQ-003"]),
        ("Feature: f\n  Background:\n    When x\n  Scenario: s\n    Given a\n    When b\n    Then c\n", ["GK-SEQ-006"]),
        ("Feature: f\n  Scenario Outline: s\n    Given <a>\n    When b\n    Then c\n", ["GK-OUT-001"]),
        (
            "Feature: f\n  Scenario Outline: s\n    Given <a>\n    When <b>\n    Then c\n"
            "    Examples:\n      | a |\n      | 1 |\n",
            ["GK-OUT-002"],
        ),
        (
            "Feature: f\n  Scenario Outline: s\n    Given <a>\n    When b\n    Then c\n    Examples:\n      | a |\n",
            ["GK-OUT-003"],
        ),
        ("# language: fr\nFonctionnalité: f\n  Scénario: s\n    Soit a\n    Quand b\n    Alors c\n", ["GK-LANG-001"]),
    ],
)
def test_errors(src, codes):
    r = gherkin.check(src)
    assert not r.conformant
    assert sorted(r.codes) == sorted(codes), r.to_dict()


@pytest.mark.parametrize(
    "src,codes",
    [
        ("Feature: f\n  Scenario: s\n    When b\n    Then c\n", ["GK-SEQ-003"]),
        ("Feature: f\n  Scenario: s\n    Free text here\n    Given a\n    When b\n    Then c\n", ["GK-STY-001"]),
        ("Feature: f\n  Scenario: s\n    * a\n    When b\n    Then c\n", ["GK-STY-002", "GK-SEQ-003"]),
        (
            "Feature: f\n  Scenario: s\n    Given a\n    When b\n    Then c\n"
            "  Scenario: S\n    Given a\n    When b\n    Then c\n",
            ["GK-STR-006"],
        ),
        ("Feature: f\n  Scenario: s\n    Given a\n    When b\n" + "    Then c\n" * 11, ["GK-STY-003"]),
    ],
)
def test_warnings(src, codes):
    r = gherkin.check(src)
    assert r.conformant, r.to_dict()
    assert sorted(r.codes) == sorted(codes), r.to_dict()


def test_parse_error_has_location():
    r = gherkin.check("Feature: f\n  Scenario: s\n    Given a\nFeature: g\n")
    assert r.codes and r.codes[0] == "GK-PARSE-001"
    assert r.defects[0].line is not None


def test_every_defect_code_is_documented():
    codes = set(gherkin.default_profile().defects)
    assert all(c.startswith("GK-") for c in codes)
