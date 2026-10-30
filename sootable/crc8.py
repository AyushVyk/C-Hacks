def crc8(data: bytes) -> int:
    """CRC-8, polynomial 0x07, init 0x00, no reflection, no final XOR.

    A one-byte checksum added to every frame. The receiver recomputes it; any flipped bit changes the result, so a
    frame damaged on the radio link is rejected instead of being saved as a wrong reading.
    """
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc
