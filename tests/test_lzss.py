from __future__ import annotations

import unittest

from fallout1resource.lzss import LzssError, decompress_dat1_payload, decompress_lzss_block


class LzssTests(unittest.TestCase):
    def test_decompresses_literal_block(self) -> None:
        self.assertEqual(decompress_lzss_block(b"\x07xyz", max_output=3), b"xyz")

    def test_decompresses_dat1_compressed_block(self) -> None:
        self.assertEqual(decompress_dat1_payload(b"\x00\x04\x07xyz", expected_size=3), b"xyz")

    def test_copies_dat1_negative_uncompressed_block(self) -> None:
        self.assertEqual(decompress_dat1_payload(b"\xFF\xFDxyz", expected_size=3), b"xyz")

    def test_rejects_output_larger_than_declared(self) -> None:
        with self.assertRaises(LzssError):
            decompress_dat1_payload(b"\x00\x04\x07xyz", expected_size=2)

    def test_rejects_truncated_token(self) -> None:
        with self.assertRaises(LzssError):
            decompress_lzss_block(b"\x00\x01", max_output=10)


if __name__ == "__main__":
    unittest.main()
