#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seat_key() / parse_seat() 的測試：座號只有一種寫法（兩位數字字串）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import seats


class TestSeatKey(unittest.TestCase):
    def test_int_forms(self):
        self.assertEqual(seats.seat_key(1), "01")
        self.assertEqual(seats.seat_key(9), "09")
        self.assertEqual(seats.seat_key(25), "25")
        self.assertEqual(seats.seat_key(40), "40")

    def test_out_of_range(self):
        with self.assertRaises(ValueError):
            seats.seat_key(0)
        with self.assertRaises(ValueError):
            seats.seat_key(41)
        with self.assertRaises(ValueError):
            seats.seat_key(-1)

    def test_non_numeric(self):
        with self.assertRaises(ValueError):
            seats.seat_key("abc")

    def test_bool_rejected(self):
        with self.assertRaises(ValueError):
            seats.seat_key(True)

    def test_fraction_rejected(self):
        with self.assertRaises(ValueError):
            seats.seat_key(1.5)


class TestParseSeat(unittest.TestCase):
    def test_accepted_forms(self):
        self.assertEqual(seats.parse_seat(1), "01")
        self.assertEqual(seats.parse_seat("1"), "01")
        self.assertEqual(seats.parse_seat("01"), "01")
        self.assertEqual(seats.parse_seat(25), "25")
        self.assertEqual(seats.parse_seat("25"), "25")
        self.assertEqual(seats.parse_seat(" 7 "), "07")

    def test_rejected_forms(self):
        for bad in ("座01", "1.0", "", " ", "041", None, 1.5, True, [1], "-1", "1a"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    seats.parse_seat(bad)


if __name__ == "__main__":
    unittest.main()
