import unittest

from fastapi import HTTPException

from backend.profile_height import height_values


class ProfileHeightTests(unittest.TestCase):
    def test_automatic_ignores_client_height_and_recomputes_on_stature_change(self):
        profile = height_values({'stature_m': 1.75, 'table_height_mode': 'automatic', 'table_height_m': .3})
        self.assertEqual(profile['table_height_m'], 1.05)
        self.assertEqual(profile['table_height_rule'], 'stature-ratio-v1')
        edited = height_values({'stature_m': 1.8}, profile)
        self.assertEqual(edited['table_height_m'], 1.08)
        self.assertEqual(edited['table_height_mode'], 'automatic')

    def test_manual_override_survives_stature_edit(self):
        profile = height_values({'stature_m': 1.75, 'table_height_mode': 'manual', 'table_height_m': .95})
        edited = height_values({'stature_m': 1.9}, profile)
        self.assertEqual(edited['table_height_m'], .95)
        self.assertIsNone(edited['table_height_rule'])

    def test_legacy_explicit_height_is_manual_without_invented_stature(self):
        profile = height_values({'table_height_m': .95})
        self.assertIsNone(profile['stature_m'])
        self.assertEqual(profile['table_height_mode'], 'manual')
        current = height_values({'stature_m': 1.75})
        override = height_values({'table_height_m': 1.0}, current)
        self.assertEqual(override['table_height_mode'], 'manual')
        self.assertEqual(override['stature_m'], 1.75)

    def test_invalid_or_missing_stature_cannot_enable_automatic(self):
        for value in (None, True, '1.75', float('nan'), float('inf'), .99, 2.31):
            with self.subTest(value=value), self.assertRaises(HTTPException):
                height_values({'stature_m': value, 'table_height_mode': 'automatic'})
        for body in ({'table_height_m': True}, {'table_height_m': float('nan')},
                     {'table_height_m': 2.1}, {'table_height_mode': 'unknown'}):
            with self.subTest(body=body), self.assertRaises(HTTPException):
                height_values(body)


if __name__ == '__main__':
    unittest.main()
