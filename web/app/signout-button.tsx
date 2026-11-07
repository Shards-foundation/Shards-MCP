"use client";
import { signOut } from "next-auth/react";

export function SignOutButton() {
  return <button type="button" className="action"
    onClick={() => void signOut({ callbackUrl: "/signin" })}>Sign out</button>;
}
