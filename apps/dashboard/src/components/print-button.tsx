"use client";

import { Button } from "@agentry/ui";

export function PrintButton() {
  return <Button variant="secondary" size="sm" onClick={() => window.print()}>Download PDF</Button>;
}
