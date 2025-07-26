"""Utility helpers for interpreting reader output.

This module contains a small state machine for collecting the payload lines
returned from the reader and a set of decoders that translate payloads for
specific commands.  The built in decoders handle the ``.vr`` (version
information) and ``.bl`` (battery information) operations, but the design is
extensible to support additional commands with different payload structures.
"""

from typing import Dict, List, Optional
from abc import ABC, abstractmethod
from dataclasses import dataclass

from constants import VERSION_LABELS, BATTERY_LABELS


class PayloadDecoder(ABC):
    """Interface for command-specific payload decoders."""

    command: str

    @abstractmethod
    def parse(
        self,
        lines: List[str],
        version_info: Dict[str, str],
        battery_info: Dict[str, str],
    ) -> None:
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
    ) -> None:
        for line in lines:
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            label = VERSION_LABELS.get(key.strip(), key.strip())
            version_info[label] = val.strip()


class BatteryDecoder(PayloadDecoder):
    """Decoder for the ``.bl`` (battery level) command."""

    command = ".bl"

    def parse(
        self,
        lines: List[str],
        version_info: Dict[str, str],
        battery_info: Dict[str, str],
    ) -> None:
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


DECODERS: Dict[str, PayloadDecoder] = {
    d.command: d
    for d in (
        VersionDecoder(),
        BatteryDecoder(),
    )
}


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
) -> None:
    """Parse *lines* for a command using the registered decoder.

    Payloads for ``.vr`` contain key/value pairs describing firmware and
    hardware versions while ``.bl`` returns battery statistics. Additional
    commands can be supported by subclassing :class:`PayloadDecoder` and
    adding the decoder instance to :data:`DECODERS`.
    """

    decoder = DECODERS.get(command)
    if not decoder:
        return
    decoder.parse(lines, version_info, battery_info)
