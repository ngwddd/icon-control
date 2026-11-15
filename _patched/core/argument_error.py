"""Errors a caller can act on, without leaking type text or credentials."""
from __future__ import annotations


class ArgumentError(ValueError):
    """A tool refused its arguments for a reason the caller can fix.

    ``code`` is a stable machine-readable string, ``hint`` says what to do next and
    ``data`` carries the numbers (the point, the screen box). Anything else stays a
    plain exception and is masked by the MCP layer, because its message may quote
    typed text.
    """

    def __init__(self, message: str, *, code: str = "invalid_argument",
                 hint: str = "", **data):
        super().__init__(message)
        self.code = code
        self.hint = hint
        self.data = data

    def payload(self, tool: str | None = None) -> dict:
        body = {"success": False, "ok": False, "blocked": False,
                "code": self.code, "error": str(self), "hint": self.hint}
        if tool:
            body["tool"] = tool
        if self.data:
            body["data"] = self.data
        return body
