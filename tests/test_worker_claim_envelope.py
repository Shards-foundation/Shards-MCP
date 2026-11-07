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
                     {"id": "task-1"}, {"id": "task-1", "input": None}):
            with self.subTest(task=task):
                client = StubClient({"claimed": True, "task": task})
                if isinstance(task, dict) and task.get("id") == "task-1" and "input" in task:
                    # A present null input is a valid envelope; the operation
                    # validator will reject it after the checkpoint.
                    continue
                with self.assertRaisesRegex(RuntimeError, "invalid claimed task"):
                    process_once(client)
                self.assertEqual([name for name, _ in client.calls],
                                 ["agent_heartbeat", "task_claim_next"])

    def test_empty_claim_exits_without_side_effect(self):
        client = StubClient({"claimed": False})
        self.assertEqual(process_once(client), 0)
        self.assertEqual([name for name, _ in client.calls],
                         ["agent_heartbeat", "task_claim_next"])


if __name__ == "__main__":
    unittest.main()
