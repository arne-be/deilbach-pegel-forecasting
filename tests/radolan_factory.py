"""Builds synthetic RADOLAN RW files in DWD's layout for tests."""

import struct
from datetime import datetime

CELLS = 900 * 900


def rw_file(
    product_time: datetime,
    words: dict[int, int] | None = None,
    product: str = "RW",
    version: int = 3,
    grid: str = "900x 900",
    cells: int = CELLS,
) -> bytes:
    """An RW file for `product_time` with all cells 0 except `words` (flat index: raw word)."""
    stamp = f"{product_time:%d%H%M}10000{product_time:%m%y}"
    tail = f"VS {version}SW   2.29.1PR E-01INT  60GP {grid}MF 00000001MS 10<ess,ros> "
    # BY is the whole file size; seven digits like real files, so the header length is fixed.
    header_length = len(f"{product}{stamp}BY0000000{tail}") + 1
    header = f"{product}{stamp}BY{header_length + 2 * cells:07d}{tail}".encode("ascii") + b"\x03"
    data = bytearray(2 * cells)
    for cell, word in (words or {}).items():
        struct.pack_into("<H", data, 2 * cell, word)
    return header + bytes(data)
