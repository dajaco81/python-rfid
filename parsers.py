# parsers.py
# This file contains functions for parsing responses from the RFID reader.

import re
from typing import NamedTuple, Optional, Dict, Any


class Response(NamedTuple):
    command: Optional[str]
    ok: bool
    error: Optional[str]
    payload: Optional[str]


class ResponseParser:
    """Stateful parser for multi-line reader responses."""
    
    def __init__(self):
        self.reset()
        
    def reset(self):
        self.command = None
        self.ok = None
        self.error = None
        self.payload = []

    def feed(self, line: str) -> Optional[Response]:
        """
        Feed a single line of output and return a Response object when
        the response is complete. Returns None otherwise.
        """
        line = line.strip()
        
        if line.startswith('OK:') and self.command:
            response = Response(self.command, True, None, "\n".join(self.payload))
            self.reset()
            return response
        
        if line.startswith('ER:') and self.command:
            error_code = line.replace('ER:', '').strip()
            response = Response(self.command, False, error_code, "\n".join(self.payload))
            self.reset()
            return response
            
        if self.command is None:
            # We haven't started parsing a response yet,
            # so the line must be the command.
            if line.startswith('.') or line.startswith('+'):
                self.command = line
                self.payload = []
            else:
                # This isn't a command, so it's probably
                # a miscellaneous line or an inventory tag.
                return None
        
        # We are in the middle of a response, so collect the payload.
        if self.command and not (line.startswith('OK:') or line.startswith('ER:')):
            self.payload.append(line)
            return None
        
        return None


def parse_payload(command: str, payload: str, app_data: Dict[str, Any]) -> None:
    """
    Parses a specific payload from a command response and updates application data.
    """
    if command.startswith('.vr'):
        # Parse version info
        version_data = {}
        for line in payload.splitlines():
            if ':' in line:
                key, value = line.split(':', 1)
                version_data[key.strip()] = value.strip()
        app_data['version_info'].update(version_data)
        
    elif command.startswith('.bl'):
        # Parse battery info
        battery_data = {}
        for line in payload.splitlines():
            if ':' in line:
                key, value = line.split(':', 1)
                battery_data[key.strip()] = value.strip()
        app_data['battery_info'].update(battery_data)
        
    # Add other command parsers here as needed.
