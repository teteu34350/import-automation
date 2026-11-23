import os
import secrets
import unittest
import uuid

from credentials import delete_password, read_password, save_password


@unittest.skipUnless(os.name == "nt", "O Gerenciador de Credenciais exige Windows.")
class CredentialStoreTests(unittest.TestCase):
    def test_password_round_trip(self):
        target = f"PMSReportAutomation-test-{uuid.uuid4()}"
        password = secrets.token_urlsafe(24)
        try:
            save_password(target, "test@example.com", password)
            self.assertEqual(read_password(target), password)
        finally:
            delete_password(target)
        self.assertIsNone(read_password(target))


if __name__ == "__main__":
    unittest.main()
