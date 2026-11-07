"""A failed gateway call must never be mistaken for a task validation error."""
import unittest

from shards_mcp.worker import process_once


class CompletionClient:
    def __init__(self, failure=None, payload=None, error_type=RuntimeError):
        self.failure = failure
        self.error_type = error_type
        self.payload = {"action": "echo", "data": "ok"} if payload is None else payload
        self.calls = []
        self.claims = 0

    def call(self, name, args):
        self.calls.append((name, args))
        if name == "task_claim_next":
            self.claims += 1
            return ({"claimed": True, "task": {"id": "t-1", "input": self.payload}}
                    if self.claims == 1 else {"claimed": False})
        if name == self.failure:
            raise self.error_type("simulated gateway failure")
        return {"ok": True}


class WorkerCompletionSafetyTests(unittest.TestCase):
    def test_successful_completion_runtime_error_is_not_retried(self):
        client = CompletionClient(failure="task_complete")
        with self.assertRaisesRegex(RuntimeError, "simulated gateway failure"):
            process_once(client)
        self.assertEqual(sum(name == "task_complete" for name, _ in client.calls), 1)
        self.assertIs(client.calls[-1][1]["success"], True)

    def test_completion_value_error_cannot_trigger_second_completion(self):
        # Regression for the original broad except(ValueError, TypeError):
        # a future gateway adapter could raise ValueError while completing.
        client = CompletionClient(failure="task_complete", error_type=ValueError)
        with self.assertRaisesRegex(ValueError, "simulated gateway failure"):
            process_once(client)
        completions = [args for name, args in client.calls if name == "task_complete"]
        self.assertEqual(len(completions), 1)
        self.assertIs(completions[0]["success"], True)

    def test_checkpoint_runtime_error_does_not_complete_task(self):
        client = CompletionClient(failure="checkpoint_write")
        with self.assertRaisesRegex(RuntimeError, "simulated gateway failure"):
            process_once(client)
        self.assertFalse(any(name == "task_complete" for name, _ in client.calls))

    def test_local_validation_error_reports_failure_once(self):
        client = CompletionClient(payload={"action": "unsupported"})
        self.assertEqual(process_once(client), 1)
        completions = [args for name, args in client.calls if name == "task_complete"]
        self.assertEqual(len(completions), 1)
        self.assertIs(completions[0]["success"], False)
        self.assertIn("error", completions[0]["result"])

    def test_successful_operation_completes_once(self):
        client = CompletionClient()
        self.assertEqual(process_once(client), 1)
        completions = [args for name, args in client.calls if name == "task_complete"]
        self.assertEqual(len(completions), 1)
        self.assertIs(completions[0]["success"], True)


if __name__ == "__main__":
    unittest.main()
