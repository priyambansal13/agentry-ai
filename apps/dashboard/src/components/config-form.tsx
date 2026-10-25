"use client";

import { Button, Input, Label, Select } from "@agentry/ui";
import { useState, useTransition } from "react";
import { updateAutomationConfig } from "@/app/(app)/actions";

/** A settings form generated from the automation's JSON Schema (Pydantic). Fields marked editable_by: "agentry"
 *  are read-only for clients; changing them goes through a change request to Agentry. */
type Prop = {
  title?: string; description?: string; type?: string; enum?: string[]; minimum?: number; maximum?: number;
  items?: { type?: string }; prefixItems?: { type?: string }[]; anyOf?: Prop[]; editable_by?: "client" | "agentry";
  enum_labels?: Record<string, string>; // readable names for choices (json_schema_extra on the Pydantic field)
};
type Schema = { properties: Record<string, Prop> };

function base(p: Prop): Prop {
  return p.anyOf ? { ...p, ...(p.anyOf.find((x) => x.type !== "null") ?? {}) } : p;
}

export function ConfigForm({ automationKey, schema, value, isStaff, canEdit }: {
  automationKey: string; schema: Schema; value: Record<string, unknown>; isStaff: boolean; canEdit: boolean;
}) {
  const [draft, setDraft] = useState<Record<string, unknown>>(value);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, start] = useTransition();
  const editable = (p: Prop) => canEdit && (isStaff || p.editable_by === "client");
  const changed = Object.keys(draft).filter((k) => JSON.stringify(draft[k]) !== JSON.stringify(value[k]));

  function save() {
    start(async () => {
      const r = await updateAutomationConfig(automationKey, Object.fromEntries(changed.map((k) => [k, draft[k]])));
      setMsg(r.ok ? { ok: true, text: "Saved" } : { ok: false, text: r.error });
    });
  }

  return (
    <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); save(); }}>
      {Object.entries(schema.properties).map(([key, raw]) => {
        const p = base(raw);
        const id = `cfg-${key}`;
        const disabled = !editable(raw);
        const v = draft[key];
        const set = (nv: unknown) => setDraft((d) => ({ ...d, [key]: nv }));
        let field: React.ReactNode;
        if (p.type === "boolean") {
          field = (
            <label className="flex items-center gap-3 text-sm">
              <input id={id} type="checkbox" checked={Boolean(v)} disabled={disabled} onChange={(e) => set(e.target.checked)} className="h-5 w-5 accent-[var(--ink)]" />
              {p.title}
            </label>
          );
        } else if (p.enum) {
          field = <Select id={id} value={String(v ?? "")} disabled={disabled} onChange={(e) => set(e.target.value)}>{p.enum.map((o) => <option key={o} value={o}>{p.enum_labels?.[o] ?? o}</option>)}</Select>;
        } else if (p.type === "integer" || p.type === "number") {
          field = <Input id={id} type="number" min={p.minimum} max={p.maximum} value={v == null ? "" : String(v)} disabled={disabled}
            onChange={(e) => set(e.target.value === "" ? null : Number(e.target.value))} />;
        } else if (p.prefixItems?.length === 2) {
          const pair = (v as string[] | undefined) ?? ["", ""];
          field = (
            <div className="flex items-center gap-2">
              <Input id={id} type="time" value={pair[0]} disabled={disabled} onChange={(e) => set([e.target.value, pair[1]])} />
              <span className="text-muted">to</span>
              <Input type="time" aria-label={`${p.title} end`} value={pair[1]} disabled={disabled} onChange={(e) => set([pair[0], e.target.value])} />
            </div>
          );
        } else if (p.type === "array") {
          field = <Input id={id} value={((v as string[]) ?? []).join(", ")} disabled={disabled} placeholder="comma separated"
            onChange={(e) => set(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />;
        } else {
          field = <Input id={id} value={String(v ?? "")} disabled={disabled} onChange={(e) => set(e.target.value || null)} />;
        }
        return (
          <div key={key}>
            {p.type !== "boolean" && <Label htmlFor={id}>{p.title ?? key}</Label>}
            {field}
            <p className="mt-1 text-xs text-muted">
              {p.description}{raw.editable_by === "agentry" && !isStaff ? " Managed by Agentry: ask us to change it." : ""}
            </p>
          </div>
        );
      })}
      {canEdit && (
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={pending || changed.length === 0}>{pending ? "Saving…" : "Save settings"}</Button>
          {msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
        </div>
      )}
    </form>
  );
}
