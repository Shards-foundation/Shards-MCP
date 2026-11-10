import test from "node:test";
import assert from "node:assert/strict";
import { approvedOperator, operatorSession } from "../lib/operator-access.ts";

test("exact provider-scoped identity authorisation and immediate allowlist removal", () => {
  const grants = "github:123, discord:456";
  assert.equal(approvedOperator("github:123", grants), true);
  assert.equal(approvedOperator("discord:456", grants), true);
  assert.equal(approvedOperator("github:123", "discord:456"), false);
  for (const input of ["github:1234", "google:123", "", null, 99, "github:123\n"]) {
    assert.equal(approvedOperator(input, grants), false);
  }
});
test("operator session must contain server-generated exact boolean true", () => {
  assert.equal(operatorSession({ user: { name: "operator" }, shardsOperator: true }), true);
  for (const session of [null, {}, { user: {} }, { user: {}, shardsOperator: "true" },
    { user: {}, shardsOperator: false }, { shardsOperator: true }]) {
    assert.equal(operatorSession(session), false);
  }
});
