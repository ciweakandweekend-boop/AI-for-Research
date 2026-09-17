"""Utilities for saving an interactive terminal session to a readable text file."""

from __future__ import annotations

import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import IO, Optional


ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


class _TeeStream:
    """Mirror a stream to the terminal and to a shared plain-text log file."""

    def __init__(self, terminal: IO[str], log_file: IO[str], lock: threading.Lock):
        self.terminal = terminal
        self.log_file = log_file
        self.lock = lock

    def write(self, data: str) -> int:
        self.terminal.write(data)

        # Spinner frames use carriage returns without newlines. They are useful in
        # the live terminal but make a persisted transcript unreadable.
        if "\r" in data and "\n" not in data:
            return len(data)

        clean_data = ANSI_ESCAPE.sub("", data).replace("\r", "")
        if clean_data:
            with self.lock:
                self.log_file.write(clean_data)
                self.log_file.flush()
        return len(data)

    def flush(self) -> None:
        self.terminal.flush()
        with self.lock:
            self.log_file.flush()

    def __getattr__(self, name):
        return getattr(self.terminal, name)


class SessionOutputLogger:
    """Capture a terminal session in outputs/session_YYYYMMDD_HHMMSS.txt by default."""

    def __init__(self, output_path: Optional[str] = None):
        if output_path:
            self.path = Path(output_path).expanduser().resolve()
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.path = (Path.cwd() / "outputs" / f"session_{timestamp}.txt").resolve()

        self._log_file: Optional[IO[str]] = None
        self._original_stdout: Optional[IO[str]] = None
        self._original_stderr: Optional[IO[str]] = None
        self._lock = threading.Lock()

    def __enter__(self) -> "SessionOutputLogger":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # UTF-8 with BOM keeps the transcript portable while allowing Windows
        # PowerShell and Notepad to detect the encoding reliably.
        self._log_file = self.path.open("w", encoding="utf-8-sig", newline="\n")
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        sys.stdout = _TeeStream(self._original_stdout, self._log_file, self._lock)
        sys.stderr = _TeeStream(self._original_stderr, self._log_file, self._lock)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._original_stdout is not None:
            sys.stdout = self._original_stdout
        if self._original_stderr is not None:
            sys.stderr = self._original_stderr
        if self._log_file is not None:
            self._log_file.flush()
            self._log_file.close()

    def log_user_input(self, user_input: str) -> None:
        """Record text that the terminal itself echoes but Python does not receive as output."""
        if self._log_file is None:
            return
        with self._lock:
            self._log_file.write(f"{user_input}\n")
            self._log_file.flush()
