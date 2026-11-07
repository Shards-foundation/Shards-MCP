"""Gateway doctor origin validation must fail closed before network access."""
import unittest

from shards_mcp.doctor import DiagnosticError, _validate_gateway_url


class DoctorOriginTests(unittest.TestCase):
    def test_accepts_valid_local_and_remote_origins(self):
        for value in (
            "http://localhost:8080",
            "http://127.0.0.1:8080/",
            "http://[::1]:8080",
            "https://gateway.example.test",
            "https://gateway.example.test:443/",
        ):
            with self.subTest(value=value):
                self.assertEqual(_validate_gateway_url(value), value.rstrip("/"))

    def test_rejects_malformed_or_ambiguous_origins(self):
        for value in (
            "", " https://gateway.example.test", "https://gateway.example.test ",
            "https://gateway.example.test\n", "https://gate\tway.example.test",
            "https://gateway.example.test\r.evil.test",
            "https://gateway.example.test\\@evil.test",
            "https://gateway.example.test:abc",
            "https://gateway.example.test:65536",
            "https://gateway.example.test:0",
            "https://[::1",
            "http://[::1]evil:8080",
            "http://[::1]evil",
            "https://gate\u00a0way.example.test",
            "https://gateway.example.test\u2028",
            "https://user:password@gateway.example.test",
            "https://gateway.example.test/path",
            "https://gateway.example.test?query=1",
            "https://gateway.example.test#fragment",
            "http://gateway.example.test",
        ):
            with self.subTest(value=value):
                with self.assertRaises(DiagnosticError):
                    _validate_gateway_url(value)

    def test_non_string_input_fails_with_diagnostic_error(self):
        for value in (None, 123, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(DiagnosticError):
                    _validate_gateway_url(value)


if __name__ == "__main__":
    unittest.main()
