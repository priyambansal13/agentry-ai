import type { Metadata } from "next";
import { BalanceConfirm } from "@/components/balance-confirm";

export const metadata: Metadata = { title: "Balance confirmation", robots: { index: false, follow: false } };

/** A debtor / creditor confirming their balance directly to the auditor (backend automations/ca/confirmations.py). */
export default async function ConfirmPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <BalanceConfirm token={token} />;
}
