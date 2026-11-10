/** Only stable provider-subject identities can be explicitly granted console authority. */
export function approvedOperator(identity: unknown, configured: string | undefined): boolean {
  if (typeof identity !== "string" || !identity || identity.includes(",") || identity.includes("\\n")) return false;
  return new Set((configured ?? "").split(",").map(s => s.trim()).filter(Boolean)).has(identity);
}

export function operatorSession(session: unknown): boolean {
  if (typeof session !== "object" || session === null || Array.isArray(session)) return false;
  const value = session as { shardsOperator?: unknown; user?: unknown };
  if (value.shardsOperator !== true || typeof value.user !== "object" ||
      value.user === null || Array.isArray(value.user)) return false;
  const user = value.user as { email?: unknown; name?: unknown };
  return (typeof user.email === "string" && user.email.trim().length > 0) ||
    (typeof user.name === "string" && user.name.trim().length > 0);
}
