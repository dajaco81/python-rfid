"""Utility functions for interpreting reader output."""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

from constants import VERSION_LABELS, BATTERY_LABELS


def parse_line(
    line: str,
    current_cmd: Optional[str],
    silent_queue: List[str],
    version_info: Dict[str, str],
    battery_info: Dict[str, str],
) -> Tuple[Optional[str], bool, bool, bool]:
    """Parse a response line and update info dicts.

    Returns updated current_cmd, whether current_cmd is silent, and flags
    indicating whether version or battery info changed.
    """
    version_updated = False
    battery_updated = False
    current_silent = False

    if line.startswith("CS:"):
        current_cmd = line[4:].strip()
    elif silent_queue and line.strip() == silent_queue[0]:
        # Some readers simply echo the command without a prefix
        current_cmd = line.strip()

    current_silent = bool(silent_queue and silent_queue[0] == current_cmd)

    if line == "OK:" or line.startswith("ER:"):
        pass
    elif current_cmd == ".vr":
        if ":" in line:
            k, v = line.split(":", 1)
            label = VERSION_LABELS.get(k.strip(), k.strip())
            version_info[label] = v.strip()
            version_updated = True
    elif current_cmd == ".bl":
        if ":" in line:
            k, v = line.split(":", 1)
            field = k.strip()
            label = BATTERY_LABELS.get(field, field)
            val = v.strip()
            if field == "BV":
                battery_info[label] = f"{val}mV"
            elif field in ("PC", "BP"):
                battery_info[label] = val if val.endswith("%") else f"{val}%"
            else:
                battery_info[label] = val
            battery_updated = True

    return current_cmd, current_silent, version_updated, battery_updated


@dataclass
class CommandResponse:
    """Container for a complete command response."""

    command: str
    payload: List[str]
    ok: bool
    error: Optional[str] = None


class ResponseParser:
    """Stateful parser for device output following the CS/OK/ER pattern."""

    def __init__(self) -> None:
        self._command: Optional[str] = None
        self._payload: List[str] = []

    @property
    def command(self) -> Optional[str]:
        """Return the command currently being parsed, if any."""
        return self._command

    def feed(self, line: str) -> Optional[CommandResponse]:
        """Feed a single line of text to the parser.

        When a full response is collected this returns a :class:`CommandResponse`
        instance; otherwise ``None`` is returned.
        """
        if line.startswith("CS:"):
            self._command = line[3:].strip()
            self._payload = []
            return None

        if line.startswith("OK:"):
            if self._command is None:
                return None
            resp = CommandResponse(self._command, self._payload, True)
            self._command = None
            self._payload = []
            return resp

        if line.startswith("ER:"):
            if self._command is None:
                return None
            err = line[3:].strip()
            resp = CommandResponse(self._command, self._payload, False, err)
            self._command = None
            self._payload = []
            return resp

        if self._command is not None:
            self._payload.append(line)
        return None


def parse_payload(
    command: str,
    lines: List[str],
    version_info: Dict[str, str],
    battery_info: Dict[str, str],
) -> Tuple[bool, bool]:
    """Parse response payload lines for known commands."""

    version_updated = False
    battery_updated = False

    if command == ".vr":
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                label = VERSION_LABELS.get(k.strip(), k.strip())
                version_info[label] = v.strip()
                version_updated = True

    elif command == ".bl":
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                field = k.strip()
                label = BATTERY_LABELS.get(field, field)
                val = v.strip()
                if field == "BV":
                    battery_info[label] = f"{val}mV"
                elif field in ("PC", "BP"):
                    battery_info[label] = val if val.endswith("%") else f"{val}%"
                else:
                    battery_info[label] = val
                battery_updated = True

    return version_updated, battery_updated
