import type { Metadata } from "next";
import { ClientPortal } from "@/components/client-portal";

export const metadata: Metadata = { title: "Client portal", robots: { index: false, follow: false } };

/** A CA firm's client portal: the firm's brand, not Agentry's site chrome. */
export default async function PortalPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <ClientPortal token={token} />;
}
