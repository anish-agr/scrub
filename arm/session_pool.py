"""Instruction-bound sessions, serialized by Arm's operation lock.

Only explicitly prepared instructions are retained across instruction changes;
ordinary on-demand use keeps its previous single-session behavior.
"""
from __future__ import annotations

import time


class SessionPool:
    def __init__(self, factory, context, cancelled=lambda: False):
        self.factory = factory
        self.context = context
        self.cancelled = cancelled
        self._context = None
        self.entries = {}
        self.prepared = set()
        self.current = None

    @staticmethod
    def expired(session):
        return bool(getattr(session, "closed", False)) or time.monotonic() >= getattr(session, "expires_at", float("inf"))

    def sync_context(self):
        context = self.context()
        if context != self._context:
            self.close()
            self._context = context

    def discard(self, session):
        for instruction, existing in list(self.entries.items()):
            if existing is session:
                del self.entries[instruction]
                self.prepared.discard(instruction)
                if self.current == instruction:
                    self.current = None
        session.close()

    def get(self, instruction):
        self.sync_context()
        if self.cancelled():
            raise RuntimeError("Arm is frozen; no session requested")
        if self.current and self.current != instruction and self.current not in self.prepared:
            self.discard(self.entries[self.current])
        session = self.entries.get(instruction)
        was_prepared = instruction in self.prepared
        if session is not None and self.expired(session):
            self.discard(session)
            session = None
        if session is None:
            session = self.factory(instruction)
            if self.cancelled():
                session.close()
                raise RuntimeError("Arm froze while opening a session")
            self.entries[instruction] = session
            if was_prepared:
                self.prepared.add(instruction)
        self.current = instruction
        return session

    def prepare(self, instructions):
        if isinstance(instructions, (str, bytes)):
            raise ValueError("prepare expects an iterable of instruction strings, not one string")
        requested = list(instructions)
        if any(not isinstance(value, str) or not value.strip() for value in requested):
            raise ValueError("Prepared instructions must be nonempty strings")
        requested = list(dict.fromkeys(requested))
        self.sync_context()
        if self.cancelled():
            raise RuntimeError("Arm is frozen; preparation cancelled")
        replacement, opened = {}, []
        try:
            for instruction in requested:
                if self.cancelled():
                    raise RuntimeError("Arm froze during preparation")
                session = self.entries.get(instruction)
                if session is None or self.expired(session):
                    session = self.factory(instruction)
                    opened.append(session)
                replacement[instruction] = session
                if self.cancelled():
                    raise RuntimeError("Arm froze during preparation")
        except BaseException:
            # Roll back only this attempt. Existing good sessions remain usable.
            for session in opened:
                session.close()
            raise
        for instruction, session in list(self.entries.items()):
            if replacement.get(instruction) is not session:
                self.discard(session)
        self.entries = replacement
        self.prepared = set(requested)
        if self.current not in self.entries:
            self.current = None
        return requested  # never expose credentials in the return value

    def close(self):
        sessions = list(self.entries.values())
        self.entries = {}
        self.prepared.clear()
        self.current = None
        for session in sessions:
            session.close()
