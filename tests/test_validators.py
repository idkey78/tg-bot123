import unittest

from bot.utils.validators import validate_practical_price, validate_student_field


class ValidatorTests(unittest.TestCase):
    def test_price_accepts_integers_between_one_and_five_hundred(self):
        for text, price in (("1", 1), ("50", 50), (" 75 ", 75), ("500", 500), ("050", 50)):
            with self.subTest(text=text):
                self.assertEqual(validate_practical_price(text), price)

    def test_price_rejects_invalid_values(self):
        for text in ("", " ", "0", "501", "-50", "5 0", "1.5", "50 грн", "²", "２", "9" * 5000):
            with self.subTest(text=text[:30]):
                self.assertIsNone(validate_practical_price(text))

    def test_student_fields_normalize_whitespace_and_reject_empty_or_command_input(self):
        self.assertEqual(validate_student_field("  КІ-21 ", 30), "КІ-21")
        self.assertEqual(validate_student_field("Іваненко   Іван", 100), "Іваненко Іван")
        for text in (None, "   ", "/start", "!", "x" * 31):
            with self.subTest(text=text):
                self.assertIsNone(validate_student_field(text, 30))
