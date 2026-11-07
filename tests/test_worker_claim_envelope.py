"""Malformed claim responses must never execute or acknowledge tasks."""
import unittest

from shards_mcp.worker import process_once


class StubClient:
    def __init__(self, claim):
        self.claim = claim
        self.calls = []

    def call(self, name, args):
        self.calls.append((name, args))
        if name == "task_claim_next":
            return self.claim
        if name == "agent_heartbeat":
            return {"healthy": True}
        raise AssertionError("unexpected side-effect call: " + name)


class WorkerClaimEnvelopeTests(unittest.TestCase):
    def test_invalid_claim_flags_fail_closed(self):
        for claim in (None, [], {}, {"claimed": 1}, {"claimed": "false"},
                      {"claimed": None}, {"claimed": True}):
            with self.subTest(claim=claim):
                client = StubClient(claim)
                with self.assertRaisesRegex(RuntimeError, "invalid task claim|invalid claimed task"):
                    process_once(client)
                self.assertEqual([name for name, _ in client.calls],
                                 ["agent_heartbeat", "task_claim_next"])

    def test_invalid_claimed_task_never_causes_side_effect(self):
        for task in (None, [], {}, {"id": ""}, {"id": 123, "input": {}},
                     {"id": "task-1"}):
            with self.subTest(task=task):
                client = StubClient({"claimed": True, "task": task})
                with self.assertRaisesRegex(RuntimeError, "invalid claimed task"):
                    process_once(client)
                self.assertEqual([name for name, _ in client.calls],
                                 ["agent_heartbeat", "task_claim_next"])

    def test_present_null_input_reports_task_validation_failure(self):
        class NullInputClient(StubClient):
            def __init__(self):
                super().__init__({"claimed": True, "task": {"id": "task-1", "input": None}})
                self.claims = 0

            def call(self, name, args):
                if name == "task_claim_next":
                    self.claims += 1
                    self.calls.append((name, args))
                    if self.claims > 1:
                        return {"claimed": False}
                    return self.claim
                if name in ("checkpoint_write", "task_complete"):
                    self.calls.append((name, args))
                    return {"ok": True}
                return super().call(name, args)

        client = NullInputClient()
        self.assertEqual(process_once(client), 1)
        self.assertEqual([name for name, _ in client.calls],
                         ["agent_heartbeat", "task_claim_next", "checkpoint_write",
                          "task_complete", "task_claim_next"])
        completion = client.calls[3][1]
        self.assertEqual(completion["task_id"], "task-1")
        self.assertIs(completion["success"], False)
        self.assertIn("error", completion["result"])

    def test_empty_claim_exits_without_side_effect(self):
        client = StubClient({"claimed": False})
        self.assertEqual(process_once(client), 0)
        self.assertEqual([name for name, _ in client.calls],
                         ["agent_heartbeat", "task_claim_next"])


if __name__ == "__main__":
    unittest.main()
