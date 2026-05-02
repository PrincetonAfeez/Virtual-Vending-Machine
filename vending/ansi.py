"""Tiny ANSI helper module."""

from __future__ import annotations


class ANSI:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def wrap(self, text: str, code: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def green(self, text: str) -> str:
        return self.wrap(text, "32")

    def yellow(self, text: str) -> str:
        return self.wrap(text, "33")

    def red(self, text: str) -> str:
        return self.wrap(text, "31")

    def dim(self, text: str) -> str:
        return self.wrap(text, "2")

    def bright(self, text: str) -> str:
        return self.wrap(text, "1")

