"""Shared result types for the deterministic conformance checkers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Defect:
    """One problem found in a statement or document.

    ``code`` is a stable identifier from the profile's defect taxonomy and is
    the label used by the golden evaluation set.
    """

    code: str
    severity: Severity
    message: str
    line: int | None = None
    column: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "severity": self.severity.value, "message": self.message}
        if self.line is not None:
            d["line"] = self.line
        if self.column is not None:
            d["column"] = self.column
        return d


@dataclass
class ConformanceResult:
    """Verdict of a checker. Conformant means no error-level defects."""

    profile: str
    profile_version: str
    defects: list[Defect] = field(default_factory=list)
    template_id: str | None = None
    slots: dict[str, str] = field(default_factory=dict)

    @property
    def conformant(self) -> bool:
        return not any(d.severity is Severity.ERROR for d in self.defects)

    @property
    def codes(self) -> list[str]:
        return [d.code for d in self.defects]

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "profile_version": self.profile_version,
            "conformant": self.conformant,
            "template_id": self.template_id,
            "slots": dict(self.slots),
            "defects": [d.to_dict() for d in self.defects],
        }
