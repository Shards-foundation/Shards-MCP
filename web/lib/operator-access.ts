/** Only stable provider-subject identities can be explicitly granted console authority. */
export function approvedOperator(identity: unknown, configured: string | undefined): boolean {
  if (typeof identity !== "string" || !identity || identity.includes(",") || identity.includes("\\n")) return false;
  return new Set((configured ?? "").split(",").map(s => s.trim()).filter(Boolean)).has(identity);
}

export function operatorSession(session: unknown): boolean {
  return typeof session === "object" && session !== null &&
    !Array.isArray(session) && (session as { shardsOperator?: unknown }).shardsOperator === true &&
    typeof (session as { user?: { email?: string; name?: string } }).user === "object";
}
