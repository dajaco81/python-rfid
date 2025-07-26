"""Utility helpers for interpreting reader output.

This module contains a small state machine for collecting the payload lines
returned from the reader and a set of decoders that translate payloads for
specific commands.  The built in decoders handle the ``.vr`` (version
information) and ``.bl`` (battery information) operations, but the design is
extensible to support additional commands with different payload structures.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from abc import ABC, abstractmethod

from constants import VERSION_LABELS, BATTERY_LABELS


@dataclass
class ParseResult:
    """Flags indicating which information dictionaries were updated."""

    version_updated: bool = False
    battery_updated: bool = False


class PayloadDecoder(ABC):
    """Interface for command-specific payload decoders."""

    command: str

    @abstractmethod
    def parse(
        self,
        lines: List[str],
        version_info: Dict[str, str],
        battery_info: Dict[str, str],
    ) -> ParseResult:
        """Decode *lines* updating info dictionaries as needed."""
        raise NotImplementedError


class VersionDecoder(PayloadDecoder):
    """Decoder for the ``.vr`` (version report) command."""

    command = ".vr"

    def parse(
        self,
        lines: List[str],
        version_info: Dict[str, str],
        battery_info: Dict[str, str],
    ) -> ParseResult:
        result = ParseResult()
        for line in lines:
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            label = VERSION_LABELS.get(key.strip(), key.strip())
            version_info[label] = val.strip()
            result.version_updated = True
        return result


class BatteryDecoder(PayloadDecoder):
    """Decoder for the ``.bl`` (battery level) command."""

    command = ".bl"

    def parse(
        self,
        lines: List[str],
        version_info: Dict[str, str],
        battery_info: Dict[str, str],
    ) -> ParseResult:
        result = ParseResult()
        for line in lines:
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            field = key.strip()
            label = BATTERY_LABELS.get(field, field)
            v = val.strip()
            if field == "BV":
                battery_info[label] = f"{v}mV"
            elif field in ("PC", "BP"):
                battery_info[label] = v if v.endswith("%") else f"{v}%"
            else:
                battery_info[label] = v
            result.battery_updated = True
        return result


DECODERS: Dict[str, PayloadDecoder] = {
    d.command: d
    for d in (
        VersionDecoder(),
        BatteryDecoder(),
    )
}


def parse_line(
    line: str,
    current_cmd: Optional[str],
    silent_queue: List[str],
    version_info: Dict[str, str],
    battery_info: Dict[str, str],
) -> Tuple[Optional[str], bool, bool, bool]:
    """Parse a single line of a streaming response.

    Parameters
    ----------
    line : str
        The raw line from the device without trailing newlines.
    current_cmd : Optional[str]
        Command currently in progress. Updated when ``CS:`` prefixes are seen
        or when the device echoes a command from ``silent_queue``.
    silent_queue : List[str]
        Commands issued without console echo. The head of the queue indicates
        the command currently considered silent.
    version_info : Dict[str, str]
        Mapping updated with fields extracted from ``.vr`` responses.
    battery_info : Dict[str, str]
        Mapping updated with fields extracted from ``.bl`` responses.

    Returns
    -------
    tuple
        ``(current_cmd, is_silent, version_changed, battery_changed)``
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
    elif current_cmd in DECODERS and ":" in line:
        result = DECODERS[current_cmd].parse([line], version_info, battery_info)
        version_updated = result.version_updated
        battery_updated = result.battery_updated

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
    """Parse *lines* for a command using the registered decoder.

    Payloads for ``.vr`` contain key/value pairs describing firmware and
    hardware versions while ``.bl`` returns battery statistics.  Additional
    commands can be supported by subclassing :class:`PayloadDecoder` and
    adding the decoder instance to :data:`DECODERS`.

    The return value is ``(version_changed, battery_changed)`` indicating which
    of the provided dictionaries were updated.  Unknown commands simply yield
    ``False, False``.
    """

    decoder = DECODERS.get(command)
    if not decoder:
        return False, False
    result = decoder.parse(lines, version_info, battery_info)
    return result.version_updated, result.battery_updated
