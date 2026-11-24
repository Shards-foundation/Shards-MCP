import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  PUBLIC_NAMES,
  BASE_PRIVATE_NAMES,
  BRIDGE_TOOL_NAME,
  expectedPrivateNames,
  assertExactNames,
} from './release_gate_names.mjs';

const workflow = readFileSync(new URL('../../.github/workflows/edge-production-release-gate.yml', import.meta.url), 'utf8');
const declared = privateNames => [
  ...PUBLIC_NAMES.map(name => ({ name, public: true })),
  ...privateNames.map(name => ({ name, public: false })),
];
const discovered = names => names.map(name => ({ name }));

test('release gate exposes a default-disabled operator-selectable bridge mode', () => {
  assert.match(workflow, /bridge_mode:/);
  assert.match(workflow, /default:\s*disabled/);
  assert.match(workflow, /-\s*disabled/);
  assert.match(workflow, /-\s*enabled/);
  assert.match(workflow, /EXPECTED_BRIDGE_MODE:\s*\$\{\{\s*inputs\.bridge_mode\s*\}\}/);
  assert.match(workflow, /release_gate_names\.mjs/);
  assert.equal(/const privateNames=\[/.test(workflow), false);
});

test('disabled mode expects exactly nine protected tools and no bridge', () => {
  const expected = expectedPrivateNames('disabled');
  assert.equal(expected.length, 9);
  assert.equal(expected.includes(BRIDGE_TOOL_NAME), false);
  assertExactNames(declared(expected), discovered(PUBLIC_NAMES), 'disabled');
});

test('enabled mode expects exactly ten protected tools including the bridge', () => {
  const expected = expectedPrivateNames('enabled');
  assert.equal(expected.length, 10);
  assert.equal(expected.includes(BRIDGE_TOOL_NAME), true);
  assertExactNames(declared(expected), discovered(PUBLIC_NAMES), 'enabled');
});

test('disabled mode rejects a status that exposes the bridge', () => {
  assert.throws(
    () => assertExactNames(declared(expectedPrivateNames('enabled')), discovered(PUBLIC_NAMES), 'disabled'),
    /not exactly 9/,
  );
});

test('enabled mode rejects a status missing the bridge', () => {
  assert.throws(
    () => assertExactNames(declared(expectedPrivateNames('disabled')), discovered(PUBLIC_NAMES), 'enabled'),
    /not exactly 10/,
  );
});

test('both modes always enforce seven public names and hide every private tool from anonymous discovery', () => {
  for (const mode of ['disabled', 'enabled']) {
    const expected = expectedPrivateNames(mode);
    assertExactNames(declared(expected), discovered(PUBLIC_NAMES), mode);
    assert.throws(
      () => assertExactNames(declared(expected), discovered([...PUBLIC_NAMES, 'shards_agent_identity']), mode),
      /Unauthenticated discovery/,
    );
    assert.throws(
      () => assertExactNames(declared([...expected, 'unexpected_tool']), discovered(PUBLIC_NAMES), mode),
      /protected tools not exactly/,
    );
  }
});

test('invalid or missing bridge mode fails closed', () => {
  assert.throws(() => expectedPrivateNames('maybe'), /Invalid bridge mode/);
  assert.throws(() => assertExactNames(declared(BASE_PRIVATE_NAMES), discovered(PUBLIC_NAMES), ''), /Invalid bridge mode/);
});
