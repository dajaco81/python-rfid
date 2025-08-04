# Python RFID GUI

A PyQt5 interface for TSL 1128 RFID readers.

## Prerequisites

- Python 3
- `pyserial`
- `PyQt5`
- `matplotlib`

## Installation

Install the dependencies with `pip`:

```bash
pip install -r requirements.txt
```

## Launching

Run the GUI application:

```bash
python run.py
```

Replace `python` with `python3` if needed.

### Console output

Commands sent to the reader appear once in the console prefixed with `>>`.

### Response parsing

The output from the reader follows a simple ``CS/OK/ER`` protocol.  Lines
starting with ``CS:`` contain the echoed command, intermediate payload lines
follow and the response terminates with either ``OK:`` or ``ER:``.  The
``parsers`` module provides a :class:`ResponseParser` that collects these lines
and delegates decoding of the payload to command specific decoders.

Three commands are currently understood:

- ``.vr`` – returns firmware and hardware version information as ``FIELD:VALUE``
  pairs.  The fields are expanded to friendly names using ``VERSION_LABELS``.
- ``.bl`` – reports battery statistics.  Fields such as ``BV`` (voltage) and
  ``BP`` (charge percentage) are normalised for display.
- ``.iv`` – performs an inventory scan.  ``EP`` lines in the payload contain
  EPC values which are tallied and displayed in the tag table.

New commands can be supported by subclassing ``PayloadDecoder`` in
``parsers.py`` and adding the instance to the ``DECODERS`` registry.

### Tag options

The GUI provides a **Zero Persistence** toggle that switches the reader to
Session&nbsp;0 for continuous tag strength updates.  In the default state the
reader uses Session&nbsp;1, causing tags to fall silent briefly after each
read.

Select a tag in the table and click **Filter Tag** to have the reader observe
only that tag.  Use **Clear Filter** to remove the filter.

The tag table tracks the minimum and maximum signal strength seen for each
tag. These values persist regardless of the limited history buffer and reset
when **Clear Tags** is used.
