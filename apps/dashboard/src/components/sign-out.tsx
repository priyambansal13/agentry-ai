"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { authClient } from "@/lib/auth-client";

export function SignOut() {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={async () => {
        await authClient.signOut();
        router.push("/sign-in");
      }}
      className="rounded-lg p-2 text-muted transition-colors hover:bg-lime-soft hover:text-ink"
      aria-label="Sign out"
      title="Sign out"
    >
      <LogOut className="h-4 w-4" />
    </button>
  );
}
