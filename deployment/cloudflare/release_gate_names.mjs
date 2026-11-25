// Exact source-branch surface. Concurrent PR #56 adds an independent public
// `shards_issue_read`; if it merges first, rebase these lists and the release
// gate to the merged surface. Never infer a deployed count from this file.
export const PUBLIC_NAMES = [
  'shards_gateway_status',
  'shards_systems_catalog',
  'shards_dns_lookup',
  'shards_skill_search',
  'shards_skill_read',
  'shards_repo_document',
  'shards_open_prs',
  'shards_pr_read',
  'shards_commit_read',
].sort();

export const BASE_PRIVATE_NAMES = [
  'shards_agent_identity',
  'shards_agents_list',
  'shards_message_send',
  'shards_message_inbox',
  'shards_task_create',
  'shards_task_inbox',
  'shards_task_get',
  'shards_task_claim',
  'shards_task_complete',
  'shards_audit_tail',
].sort();

export const BRIDGE_TOOL_NAME = 'shards_kernel_issue_label';

function sameNames(actual, expected) {
  return JSON.stringify([...actual].sort()) === JSON.stringify([...expected].sort());
}

export function expectedPrivateNames(bridgeMode) {
  if (bridgeMode === 'disabled') return [...BASE_PRIVATE_NAMES];
  if (bridgeMode === 'enabled') return [...BASE_PRIVATE_NAMES, BRIDGE_TOOL_NAME].sort();
  throw new Error('Invalid bridge mode: expected disabled or enabled');
}

export function assertExactNames(declared, discovered, bridgeMode) {
  const expectedPrivate = expectedPrivateNames(bridgeMode);
  const declaredTools = Array.isArray(declared) ? declared : [];
  const discoveredTools = Array.isArray(discovered) ? discovered : [];
  if (!sameNames(declaredTools.filter(t => t.public).map(t => t.name), PUBLIC_NAMES)) {
    throw new Error(`API status public tools not exactly ${PUBLIC_NAMES.length}`);
  }
  if (!sameNames(declaredTools.filter(t => !t.public).map(t => t.name), expectedPrivate)) {
    throw new Error(`API status protected tools not exactly ${expectedPrivate.length} for bridge ${bridgeMode}`);
  }
  if (!sameNames(discoveredTools.map(t => t.name), PUBLIC_NAMES)) {
    throw new Error(`Unauthenticated discovery not exactly ${PUBLIC_NAMES.length} public tools`);
  }
  return { publicNames: PUBLIC_NAMES, expectedPrivate, bridgeMode };
}
