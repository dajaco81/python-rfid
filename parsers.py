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

from constants import VERSION_LABELS, BATTERY_LABELS, STRENGTH_HISTORY_LEN


DecoderContext = Dict[str, Dict[str, str]]


class PayloadDecoder(ABC):
    """Interface for command-specific payload decoders."""

    command: str

    @abstractmethod
    def parse(self, lines: List[str], context: DecoderContext) -> None:
        """Decode *lines* updating *context* as needed."""
        raise NotImplementedError


class VersionDecoder(PayloadDecoder):
    """Decoder for the ``.vr`` (version report) command."""

    command = ".vr"
    target = "version_info"

    def parse(self, lines: List[str], context: DecoderContext) -> None:
        info = context.setdefault(self.target, {})
        for line in lines:
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            field = key.strip()
            label = VERSION_LABELS.get(field, field)
            v = val.strip()

            if field == "BV":
                info[label] = f"{v}mV"
            else:
                info[label] = v


class BatteryDecoder(PayloadDecoder):
    """Decoder for the ``.bl`` (battery level) command."""

    command = ".bl"
    target = "battery_info"

    def parse(self, lines: List[str], context: DecoderContext) -> None:
        info = context.setdefault(self.target, {})
        for line in lines:
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            field = key.strip()
            label = BATTERY_LABELS.get(field, field)
            v = val.strip()

            if field == "BP":
                info[label] = v if v.endswith("%") else f"{v}%"
            else:
                info[label] = v


class InventoryDecoder(PayloadDecoder):
    """Decoder for the ``.iv`` (inventory) command."""

    command = ".iv"
    count_target = "tag_counts"
    strength_target = "tag_strengths"
    # Maximum number of signal strength samples to retain per tag
    history_len = STRENGTH_HISTORY_LEN

    def parse(self, lines: List[str], context: DecoderContext) -> None:
        counts = context.setdefault(self.count_target, {})
        strengths = context.setdefault(self.strength_target, {})
        last_tag: Optional[str] = None
        for line in lines:
            if line.startswith("EP:"):
                tag = line[3:].strip()
                if tag:
                    counts[tag] = counts.get(tag, 0) + 1
                    hist = strengths.setdefault(tag, [])
                    hist.append(None)
                    if len(hist) > self.history_len:
                        hist.pop(0)
                    last_tag = tag
            elif line.startswith("RI:"):
                val_str = line[3:].strip()
                try:
                    strength = int(val_str)
                except ValueError:
                    try:
                        strength = float(val_str)
                    except ValueError:
                        strength = None
                if last_tag:
                    hist = strengths.setdefault(last_tag, [])
                    if hist:
                        if hist[-1] is None:
                            hist[-1] = strength
                        else:
                            hist.append(strength)
                            if len(hist) > self.history_len:
                                hist.pop(0)
                last_tag = None



DECODERS: Dict[str, PayloadDecoder] = {
    d.command: d
    for d in (
        VersionDecoder(),
        BatteryDecoder(),
        InventoryDecoder(),
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


def parse_payload(command: str, lines: List[str], context: DecoderContext) -> None:
    """Parse *lines* for *command* using the registered decoder.

    ``context`` is a mapping of arbitrary names to dictionaries used by
    decoders.  This allows new commands to share data stores without
    requiring the parser interface to change.
    """

    decoder = DECODERS.get(command)
    if not decoder:
        return
    decoder.parse(lines, context)
