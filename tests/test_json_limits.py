"""The exact same input-depth policy must hold across Python 3.11–3.15."""
import unittest

from shards_mcp.json_limits import MAX_JSON_DEPTH, enforce_json_depth


class JsonDepthTests(unittest.TestCase):
    def test_nested_containers_at_and_beyond_the_limit(self):
        allowed = "[" * MAX_JSON_DEPTH + "0" + "]" * MAX_JSON_DEPTH
        denied = "[" * (MAX_JSON_DEPTH + 1) + "0" + "]" * (MAX_JSON_DEPTH + 1)
        enforce_json_depth(allowed)
        enforce_json_depth(allowed.encode())
        for value in (denied, denied.encode()):
            with self.subTest(input_type=type(value).__name__):
                with self.assertRaisesRegex(ValueError, "nesting limit"):
                    enforce_json_depth(value)

    def test_json_string_delimiters_and_escaped_quotes_are_not_structure(self):
        import json
        string_value = '[' * 1200 + '{' * 1200 + r'\"escaped\"' + '}' * 1200
        payload = json.dumps({"data": string_value})
        enforce_json_depth(payload)
        enforce_json_depth(payload.encode("utf-8"))

    def test_malformed_nesting_is_rejected_without_decoder_recursion(self):
        for value in ('{"missing": [}', '["unterminated"', ']', '[[]'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    enforce_json_depth(value)

    def test_invalid_config_cannot_disable_the_guard(self):
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                enforce_json_depth("{}", max_depth=value)


if __name__ == "__main__":
    unittest.main()
