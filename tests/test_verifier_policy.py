"""Operator-assigned task verifier and classified control-domain security gates.

All identities, control-group labels, test data and credentials are synthetic.
Controller labels are operator assertions, not proof of distinct human owners.
"""
import json
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from shards_mcp.core import Gateway, GatewayError
from shards_mcp.server import TOOL_LIST
from shards_mcp.snapshots import create_snapshot, inspect_snapshot


class VerifierPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dbpath = str(Path(self.temp.name) / 'state.sqlite')
        self.secret = secrets.token_urlsafe(48)
        self.g = Gateway(self.dbpath, self.secret)
        self.root = self.g.authenticate(self.secret)
        self.creator = self.g.register(self.root, 'creator', 'test', [], ['task:create', 'task:read'])
        self.worker = self.g.register(self.root, 'worker', 'test', [], ['task:claim', 'task:update', 'task:read'])
        self.same = self.g.register(self.root, 'same-controller-reviewer', 'test', [], ['task:verify'])
        self.reviewer = self.g.register(self.root, 'independently-classified-reviewer', 'test', [], ['task:verify'])
        self.alternative = self.g.register(self.root, 'alternate-reviewer', 'test', [], ['task:verify'])
        self.no_scope = self.g.register(self.root, 'non-reviewer', 'test', [], ['task:read'])
        self.actor = self.g.authenticate(self.creator['token'])
        self.worker_actor = self.g.authenticate(self.worker['token'])
        self.reviewer_actor = self.g.authenticate(self.reviewer['token'])
        self.alternative_actor = self.g.authenticate(self.alternative['token'])
        self.same_actor = self.g.authenticate(self.same['token'])
        self.g.delegation_grant(self.root, self.creator['agent_id'], self.worker['agent_id'])
        for agent, label in (
            (self.creator, 'controller-a'),
            (self.worker, 'controller-b'),
            (self.same, 'controller-a'),
            (self.reviewer, 'controller-c'),
            (self.alternative, 'controller-d'),
            (self.no_scope, 'controller-e'),
        ):
            self.g.controller_set(self.root, agent['agent_id'], label)

    def task(self, key='case'):
        tid = self.g.task_create(self.actor, self.worker['agent_id'], {'action':'health'}, key)['task_id']
        self.g.task_claim(self.worker_actor, tid)
        self.g.task_complete(self.worker_actor, tid, True, {'ok': True})
        return tid

    def verify(self, who, task):
        return self.g.task_verify(who, task, True, {'evidence': 'independent test observation'})

    def assert_denied(self, callback, code='FORBIDDEN'):
        with self.assertRaises(GatewayError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_unassigned_scope_holder_cannot_approve_or_mutate_task(self):
        tid = self.task()
        before = self.g.audit_verify(self.root)
        self.assert_denied(lambda: self.verify(self.reviewer_actor, tid))
        self.assertEqual(self.g.task_get(self.actor, tid)['state'], 'reported')
        self.assertIsNone(self.g.verification_get(self.actor, tid)['verification'])
        self.assertEqual(self.g.audit_verify(self.root), before)

    def test_operator_only_assignment_and_controller_metadata(self):
        tid = self.task()
        self.assert_denied(lambda: self.g.verifier_assign(self.actor, tid, self.reviewer['agent_id']))
        self.assert_denied(lambda: self.g.controller_set(self.actor, self.creator['agent_id'], 'spoof-group'))
        self.assert_denied(lambda: self.g.verifier_assignments(self.actor))
        self.assert_denied(lambda: self.g.controllers(self.actor))
        self.assertEqual(self.g.verifier_assign(self.root, tid, self.reviewer['agent_id']),
                         {'task_id': tid, 'verifier': self.reviewer['agent_id'], 'unchanged': False})
        self.assertTrue(self.g.verifier_assign(self.root, tid, self.reviewer['agent_id'])['unchanged'])
        self.assertEqual(len(self.g.verifier_assignments(self.root)), 1)
        self.assertEqual(self.g.audit_list(self.root, 1)[0]['action'], 'verifier.assign')

    def test_shared_controller_credentials_are_not_independent(self):
        tid = self.task()
        self.assert_denied(lambda: self.g.verifier_assign(self.root, tid, self.same['agent_id']))
        self.assert_denied(lambda: self.g.verifier_assign(self.root, tid, self.creator['agent_id']))
        self.assert_denied(lambda: self.g.verifier_assign(self.root, tid, self.worker['agent_id']))
        with self.g.read_tx() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM verifier_assignments').fetchone()[0], 0)
        self.assertEqual(self.g.task_get(self.actor, tid)['state'], 'reported')

    def test_wrong_or_unscoped_verifier_is_rejected(self):
        tid = self.task()
        self.assert_denied(lambda: self.g.verifier_assign(self.root, tid, self.no_scope['agent_id']))
        self.g.verifier_assign(self.root, tid, self.reviewer['agent_id'])
        self.assert_denied(lambda: self.verify(self.alternative_actor, tid))
        self.assert_denied(lambda: self.verify(self.same_actor, tid))
        self.assert_denied(lambda: self.verify(self.root, tid), code="NOT_FOUND")
        self.assertEqual(self.g.task_get(self.actor, tid)['state'], 'reported')

    def test_assigned_reviewer_succeeds_once_and_audit_is_intact(self):
        tid = self.task()
        self.g.verifier_assign(self.root, tid, self.reviewer['agent_id'])
        self.assertEqual(self.verify(self.reviewer_actor, tid)['state'], 'succeeded')
        self.assert_denied(lambda: self.verify(self.reviewer_actor, tid), code='CONFLICT')
        self.assertEqual(self.g.verification_get(self.actor, tid)['verification']['verifier'], self.reviewer['agent_id'])
        self.assertTrue(self.g.audit_verify(self.root)['valid'])

    def test_controller_reclassification_invalidates_existing_assignment(self):
        tid = self.task()
        self.g.verifier_assign(self.root, tid, self.reviewer['agent_id'])
        self.g.controller_set(self.root, self.reviewer['agent_id'], 'controller-b')
        self.assert_denied(lambda: self.verify(self.reviewer_actor, tid))
        self.g.controller_set(self.root, self.reviewer['agent_id'], 'controller-c')
        self.assertEqual(self.verify(self.reviewer_actor, tid)['state'], 'succeeded')

    def test_reviewer_revocation_blocks_old_identity(self):
        tid = self.task()
        self.g.verifier_assign(self.root, tid, self.reviewer['agent_id'])
        self.g.revoke(self.root, self.reviewer['agent_id'])
        self.assert_denied(lambda: self.verify(self.reviewer_actor, tid), 'NOT_FOUND')
        self.assert_denied(lambda: self.g.verifier_assign(self.root, tid, self.reviewer['agent_id']), 'NOT_FOUND')
        self.assertEqual(self.g.task_get(self.actor, tid)['state'], 'reported')
        self.g.verifier_unassign(self.root, tid)
        self.g.verifier_assign(self.root, tid, self.alternative['agent_id'])
        self.assertEqual(self.verify(self.alternative_actor, tid)['state'], 'succeeded')

    def test_reassignment_is_explicit_and_audited_not_implicit(self):
        tid = self.task()
        self.g.verifier_assign(self.root, tid, self.reviewer['agent_id'])
        self.assert_denied(lambda: self.g.verifier_assign(self.root, tid, self.alternative['agent_id']), 'CONFLICT')
        self.assertTrue(self.g.verifier_unassign(self.root, tid)['changed'])
        self.assertFalse(self.g.verifier_unassign(self.root, tid)['changed'])
        self.g.verifier_assign(self.root, tid, self.alternative['agent_id'])
        self.assert_denied(lambda: self.verify(self.reviewer_actor, tid))
        self.assertEqual(self.verify(self.alternative_actor, tid)['state'], 'succeeded')
        self.assert_denied(lambda: self.g.verifier_unassign(self.root, tid), 'CONFLICT')
        self.assertTrue(self.g.audit_verify(self.root)['valid'])

    def test_parallel_verifier_attempts_have_one_terminal_state(self):
        tid = self.task()
        self.g.verifier_assign(self.root, tid, self.reviewer['agent_id'])
        def attempt(actor):
            try:
                return self.g.task_verify(actor, tid, True, {'evidence': 'concurrent independent check'})['state']
            except GatewayError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(attempt, (self.reviewer_actor, self.reviewer_actor,
                                              self.alternative_actor, self.reviewer_actor)))
        self.assertEqual(results.count('succeeded'), 1)
        self.assertEqual(sum(result in ('CONFLICT', 'FORBIDDEN') for result in results), 3)
        with self.g.read_tx() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM verifications WHERE task_id=?', (tid,)).fetchone()[0], 1)
        self.assertTrue(self.g.audit_verify(self.root)['valid'])

    def test_legacy_database_starts_with_no_verifier_policy_and_must_be_provisioned(self):
        tid = self.task()
        with self.g.tx() as db:
            db.execute('DROP TABLE verifier_assignments')
            db.execute('DROP TABLE agent_control_domains')
        reopened = Gateway(self.dbpath, self.secret)
        self.assertEqual(reopened.verifier_assignments(self.root), [])
        self.assertEqual(reopened.controllers(self.root), [])
        self.assert_denied(lambda: reopened.task_verify(self.reviewer_actor, tid, True,
                                                         {'proof': 'legacy approval should not pass'}))
        for agent, label in ((self.creator, 'controller-a'), (self.worker, 'controller-b'),
                             (self.reviewer, 'controller-c')):
            reopened.controller_set(self.root, agent['agent_id'], label)
        reopened.verifier_assign(self.root, tid, self.reviewer['agent_id'])
        self.assertEqual(reopened.task_verify(self.reviewer_actor, tid, True,
                                              {'proof': 'operator-classified reviewer confirmed'})['state'], 'succeeded')

    def test_restart_retains_assignments_and_group_assertions(self):
        tid = self.task()
        self.g.verifier_assign(self.root, tid, self.reviewer['agent_id'])
        reopened = Gateway(self.dbpath, self.secret)
        self.assertEqual(len(reopened.verifier_assignments(self.root)), 1)
        self.assertGreaterEqual(len(reopened.controllers(self.root)), 5)
        self.assertEqual(reopened.task_verify(self.reviewer_actor, tid, False, {'evidence': 'independent rejection'})['state'], 'failed')
        self.assertTrue(reopened.audit_verify(self.root)['valid'])

    def test_invalid_or_missing_group_fails_closed(self):
        tid = self.task()
        with self.g.tx() as db:
            db.execute('DELETE FROM agent_control_domains WHERE agent_id=?', (self.creator['agent_id'],))
        self.assert_denied(lambda: self.g.verifier_assign(self.root, tid, self.reviewer['agent_id']))
        for invalid in ('CONTROL-A', ' a ', 'operator', '__operator_control__', '*', 'ab', ''):
            with self.subTest(value=invalid):
                with self.assertRaises(GatewayError):
                    self.g.controller_set(self.root, self.creator['agent_id'], invalid)
        self.g.controller_set(self.root, self.creator['agent_id'], 'controller-a')
        self.g.verifier_assign(self.root, tid, self.reviewer['agent_id'])
        self.assertEqual(self.verify(self.reviewer_actor, tid)['state'], 'succeeded')

    def test_snapshot_includes_policy_tables(self):
        tid = self.task()
        self.g.verifier_assign(self.root, tid, self.reviewer['agent_id'])
        directory = Path(self.temp.name) / 'backups'
        directory.mkdir(mode=0o700)
        backup = directory / 'proof.sqlite'
        result = create_snapshot(self.g, self.root, str(backup))
        self.assertTrue(result['valid'])
        self.assertEqual(result['records']['verifier_assignments'], 1)
        self.assertEqual(result['records']['agent_control_domains'], 6)
        with sqlite3.connect(backup) as db:
            db.execute('DROP TABLE verifier_assignments')
        self.assert_denied(lambda: inspect_snapshot(str(backup)), 'CONFLICT')

    def test_local_cli_commands_and_no_remotely_available_policy_tools(self):
        exposed = {tool['name'] for tool in TOOL_LIST}
        self.assertFalse(any(name.startswith(('controller_', 'verifier_assign', 'verifier_unassign')) for name in exposed))
        tid = self.task()
        env = {**os.environ, 'SHARDS_DB': self.dbpath, 'SHARDS_ADMIN_TOKEN': self.secret}
        def invoke(*args):
            return subprocess.run([sys.executable, '-m', 'shards_mcp.admin', *args],
                                  env=env, capture_output=True, text=True, timeout=15)
        failed = invoke('verifier-assign', '--task-id', tid, '--verifier', 'agt_unknown')
        self.assertNotEqual(failed.returncode, 0)
        completed = invoke('verifier-assign', '--task-id', tid, '--verifier', self.reviewer['agent_id'])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['verifier'], self.reviewer['agent_id'])
        listed = invoke('verifier-list')
        self.assertEqual(len(json.loads(listed.stdout)), 1)
        controllers = invoke('controller-list')
        self.assertEqual(len(json.loads(controllers.stdout)), 6)
        revoked = invoke('verifier-unassign', '--task-id', tid)
        self.assertTrue(json.loads(revoked.stdout)['changed'])
        for output in (failed.stdout, failed.stderr, completed.stdout, completed.stderr,
                       listed.stdout, listed.stderr, controllers.stdout, controllers.stderr,
                       revoked.stdout, revoked.stderr):
            self.assertNotIn(self.secret, output)


if __name__ == '__main__':
    unittest.main()
