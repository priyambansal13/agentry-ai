/**
 * Agentry website chat widget.
 *
 *   <script src="https://…/widget.js" data-key="wk_…" data-api="https://api.…" async></script>
 *
 * Renders inside a Shadow DOM (the host site's CSS can't leak in or out), stores the conversation id + token in
 * localStorage so a reload continues the chat, and inserts every message with textContent (never innerHTML).
 */
type Config = { business: string; agent_name: string; greeting: string; color: string; logo: string | null };
type Booking = { service: string; when: string; staff: string } | null;
type Msg = { id?: string; from: "visitor" | "agent" | "human" | "system"; text: string; booking?: Booking; by?: string | null };

(() => {
  const script = document.currentScript as HTMLScriptElement | null;
  const key = script?.dataset.key;
  const api = (script?.dataset.api ?? "").replace(/\/$/, "");
  const position = script?.dataset.position === "bottom-left" ? "left" : "right";
  if (!key || !api || document.getElementById("agentry-chat-root")) return;

  const storeKey = `agentry:${key}`;
  const store = {
    get(): { id: string; token: string } | null {
      try { return JSON.parse(localStorage.getItem(storeKey) ?? "null"); } catch { return null; }
    },
    set(v: { id: string; token: string } | null) {
      try { v ? localStorage.setItem(storeKey, JSON.stringify(v)) : localStorage.removeItem(storeKey); } catch { /* private mode */ }
    },
  };

  function readableOn(hex: string): string {
    const n = parseInt(hex.replace("#", "").padEnd(6, "0").slice(0, 6), 16);
    const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
      const s = c / 255;
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    }) as [number, number, number];
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.4 ? "#111111" : "#ffffff";
  }

  const host = document.createElement("div");
  host.id = "agentry-chat-root";
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: "open" });

  const style = document.createElement("style");
  style.textContent = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
    .wrap { --brand: #c9f24b; --on-brand: #111; --bg: #fff; --ink: #111; --muted: #6b6b66; --line: #e4e4dc; --bubble: #f3f3ee;
            position: fixed; bottom: 20px; ${position}: 20px; z-index: 2147483000; color: var(--ink); }
    @media (prefers-color-scheme: dark) { .wrap { --bg: #171812; --ink: #f4f4f0; --muted: #9a9a92; --line: #2c2d25; --bubble: #23241d; } }
    .launcher { width: 60px; height: 60px; border-radius: 50%; border: 2px solid #111; background: var(--brand); color: var(--on-brand);
                cursor: pointer; display: grid; place-items: center; box-shadow: 0 8px 24px rgb(0 0 0 / .18); transition: transform .15s; }
    .launcher:hover { transform: translateY(-2px); }
    .launcher svg { width: 28px; height: 28px; }
    .panel { position: absolute; bottom: 76px; ${position}: 0; width: 370px; height: min(580px, calc(100vh - 110px));
             background: var(--bg); border: 2px solid #111; border-radius: 20px; display: none; flex-direction: column;
             overflow: hidden; box-shadow: 0 16px 48px rgb(0 0 0 / .22); }
    .panel.open { display: flex; }
    @media (max-width: 480px) {
      .panel { position: fixed; inset: 0; width: 100%; height: 100%; border-radius: 0; border: 0; }
      .wrap.open .launcher { display: none; } /* full-screen panel has its own close button */
    }
    header { background: var(--brand); color: var(--on-brand); padding: 14px 16px; display: flex; align-items: center; gap: 10px; }
    header .avatar { width: 36px; height: 36px; border-radius: 50%; background: rgb(255 255 255 / .35); display: grid; place-items: center;
                     font-weight: 700; overflow: hidden; flex-shrink: 0; }
    header .avatar img { width: 100%; height: 100%; object-fit: cover; }
    header .who { flex: 1; min-width: 0; }
    header .name { font-weight: 700; font-size: 15px; }
    header .sub { font-size: 12px; opacity: .8; }
    header button { background: transparent; border: 0; color: inherit; cursor: pointer; font-size: 22px; line-height: 1; padding: 4px; }
    .log { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
    .msg { max-width: 82%; padding: 10px 13px; border-radius: 16px; font-size: 14px; line-height: 1.45; white-space: pre-wrap; word-wrap: break-word; }
    .msg.agent, .msg.human { background: var(--bubble); align-self: flex-start; border-bottom-left-radius: 4px; }
    .msg.visitor { background: #111; color: #fff; align-self: flex-end; border-bottom-right-radius: 4px; }
    @media (prefers-color-scheme: dark) { .msg.visitor { background: #f4f4f0; color: #111; } }
    .who { align-self: flex-start; font-size: 11px; color: var(--muted); margin: 4px 0 -4px 4px; }
    .msg.system { align-self: center; font-size: 12px; color: var(--muted); background: transparent; }
    .booking { align-self: flex-start; border: 2px solid #111; background: var(--brand); color: var(--on-brand); border-radius: 14px;
               padding: 10px 13px; font-size: 13px; }
    .booking b { display: block; font-size: 14px; }
    .typing { align-self: flex-start; display: flex; gap: 4px; padding: 12px 14px; background: var(--bubble); border-radius: 16px; }
    .typing i { width: 6px; height: 6px; border-radius: 50%; background: var(--muted); animation: blink 1.2s infinite; }
    .typing i:nth-child(2) { animation-delay: .2s; } .typing i:nth-child(3) { animation-delay: .4s; }
    @keyframes blink { 0%, 80%, 100% { opacity: .25 } 40% { opacity: 1 } }
    @media (prefers-reduced-motion: reduce) { .typing i { animation: none; } .launcher { transition: none; } }
    form { display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--line); }
    textarea { flex: 1; resize: none; border: 2px solid var(--line); border-radius: 12px; padding: 10px 12px; font-size: 14px;
               max-height: 120px; background: var(--bg); color: var(--ink); outline: none; }
    textarea:focus { border-color: var(--ink); }
    form button { border: 2px solid #111; background: var(--brand); color: var(--on-brand); border-radius: 12px; padding: 0 14px;
                  font-weight: 700; cursor: pointer; }
    form button:disabled { opacity: .5; cursor: default; }
    .foot { text-align: center; font-size: 11px; color: var(--muted); padding: 0 0 8px; }
    .foot a { color: inherit; }
  `;
  root.appendChild(style);

  const wrap = document.createElement("div");
  wrap.className = "wrap";
  wrap.innerHTML = `
    <div class="panel" role="dialog" aria-modal="false" aria-label="Chat">
      <header><div class="avatar" aria-hidden="true"></div><div class="who"><div class="name"></div><div class="sub"></div></div>
        <button type="button" class="restart" aria-label="Start a new conversation" title="New conversation">↺</button>
        <button type="button" class="close" aria-label="Close chat">×</button></header>
      <div class="log" aria-live="polite"></div>
      <form><label style="position:absolute;left:-9999px" for="agentry-input">Message</label>
        <textarea id="agentry-input" rows="1" placeholder="Type a message…" maxlength="2000"></textarea>
        <button type="submit">Send</button></form>
      <div class="foot">AI assistant · powered by <a href="https://agentry.dev" target="_blank" rel="noopener">Agentry</a></div>
    </div>
    <button type="button" class="launcher" aria-label="Open chat" aria-expanded="false">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z"/></svg>
    </button>`;
  root.appendChild(wrap);

  const $ = <T extends Element>(sel: string) => wrap.querySelector(sel) as T;
  const panel = $<HTMLDivElement>(".panel");
  const launcher = $<HTMLButtonElement>(".launcher");
  const log = $<HTMLDivElement>(".log");
  const form = $<HTMLFormElement>("form");
  const input = $<HTMLTextAreaElement>("textarea");
  const send = $<HTMLButtonElement>("form button");
  let cfg: Config | null = null;
  let busy = false;
  let greeted = false; // the greeting is shown once, whether from config or from the new conversation

  function greet(text: string) {
    if (greeted) return;
    greeted = true;
    add({ from: "agent", text });
  }

  function add(m: Msg) {
    if (m.from === "human") {
      const who = document.createElement("div");
      who.className = "who";
      who.textContent = `${m.by ? `${m.by} · ` : ""}${cfg?.business ?? ""} team`;
      log.appendChild(who);
    }
    const el = document.createElement("div");
    el.className = `msg ${m.from}`;
    el.textContent = m.text;
    log.appendChild(el);
    if (m.booking) {
      const b = document.createElement("div");
      b.className = "booking";
      const title = document.createElement("b");
      title.textContent = `✓ Booked: ${m.booking.service}`;
      b.append(title, document.createTextNode(`${m.booking.when} with ${m.booking.staff}`));
      log.appendChild(b);
    }
    log.scrollTop = log.scrollHeight;
  }

  function typing(on: boolean) {
    log.querySelector(".typing")?.remove();
    if (on) {
      const t = document.createElement("div");
      t.className = "typing";
      t.setAttribute("aria-label", "typing");
      t.innerHTML = "<i></i><i></i><i></i>";
      log.appendChild(t);
      log.scrollTop = log.scrollHeight;
    }
  }

  async function call<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${api}/widget/${encodeURIComponent(key!)}${path}`, {
      ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    if (!res.ok) {
      let detail = "Something went wrong. Please try again.";
      try { detail = (await res.json()).detail ?? detail; } catch { /* not json */ }
      throw Object.assign(new Error(detail), { status: res.status });
    }
    return res.json() as Promise<T>;
  }

  async function ensureConversation(): Promise<{ id: string; token: string }> {
    const saved = store.get();
    if (saved) return saved;
    const c = await call<{ conversation_id: string; token: string; greeting: string }>("/conversations", { method: "POST" });
    const conv = { id: c.conversation_id, token: c.token };
    store.set(conv);
    greet(c.greeting);
    return conv;
  }

  async function restore() {
    const saved = store.get();
    if (!saved) return void (cfg && greet(cfg.greeting));
    try {
      const h = await call<{ messages: Msg[]; status: string }>(`/conversations/${saved.id}?token=${saved.token}`);
      greeted = true; // history starts with the greeting
      h.messages.forEach((m) => { if (m.id && m.from === "human") seenHuman.add(m.id); add(m); });
      if (h.status === "handed_off") watchForTeam();
    } catch {
      store.set(null);
      if (cfg) greet(cfg.greeting);
    }
  }

  // When a person from the business has taken over, check for their replies every few seconds.
  const seenHuman = new Set<string>();
  let watching: number | undefined;
  function watchForTeam() {
    if (watching) return;
    watching = window.setInterval(async () => {
      const saved = store.get();
      if (!saved) return void (window.clearInterval(watching), (watching = undefined));
      try {
        const h = await call<{ messages: Msg[]; status: string }>(`/conversations/${saved.id}?token=${saved.token}`);
        for (const m of h.messages) {
          if (m.from === "human" && m.id && !seenHuman.has(m.id)) { seenHuman.add(m.id); add(m); }
        }
        if (h.status !== "handed_off") { window.clearInterval(watching); watching = undefined; }
      } catch { /* network blip: try again next tick */ }
    }, 4000);
  }

  async function submit(text: string) {
    if (busy || !text.trim()) return;
    busy = true;
    send.disabled = true;
    add({ from: "visitor", text });
    input.value = "";
    typing(true);
    try {
      const conv = await ensureConversation();
      const r = await call<{ reply: string | null; booking: Booking; status?: string; handed_off?: boolean }>(`/conversations/${conv.id}/messages`, {
        method: "POST", body: JSON.stringify({ token: conv.token, text }),
      });
      typing(false);
      if (r.reply) add({ from: "agent", text: r.reply, booking: r.booking });
      else if (r.status === "handed_off") { add({ from: "system", text: "A team member will reply here soon." }); watchForTeam(); }
      if (r.status === "handed_off" || (r.reply && r.handed_off)) watchForTeam();
    } catch (e) {
      typing(false);
      add({ from: "system", text: (e as Error).message });
    } finally {
      busy = false;
      send.disabled = false;
      input.focus();
    }
  }

  function setOpen(open: boolean) {
    panel.classList.toggle("open", open);
    wrap.classList.toggle("open", open);
    launcher.setAttribute("aria-expanded", String(open));
    launcher.setAttribute("aria-label", open ? "Close chat" : "Open chat");
    if (open) input.focus();
  }

  launcher.addEventListener("click", () => setOpen(!panel.classList.contains("open")));
  $<HTMLButtonElement>(".close").addEventListener("click", () => setOpen(false));
  $<HTMLButtonElement>(".restart").addEventListener("click", () => {
    store.set(null);
    if (watching) { window.clearInterval(watching); watching = undefined; }
    log.textContent = "";
    greeted = false;
    if (cfg) greet(cfg.greeting);
  });
  wrap.addEventListener("keydown", (e) => { if (e.key === "Escape") setOpen(false); });
  form.addEventListener("submit", (e) => { e.preventDefault(); void submit(input.value); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submit(input.value); }
  });

  call<Config>("").then((c) => {
    cfg = c;
    const color = /^#[0-9a-f]{3,8}$/i.test(c.color) ? c.color : "#c9f24b";
    wrap.style.setProperty("--brand", color);
    wrap.style.setProperty("--on-brand", readableOn(color));
    $<HTMLDivElement>(".name").textContent = c.agent_name;
    $<HTMLDivElement>(".sub").textContent = `${c.business} · AI assistant`;
    const avatar = $<HTMLDivElement>(".avatar");
    if (c.logo && /^https:\/\//.test(c.logo)) {
      const img = document.createElement("img");
      img.src = c.logo;
      img.alt = "";
      avatar.appendChild(img);
    } else avatar.textContent = c.agent_name.charAt(0);
    void restore();
    (window as unknown as { AgentryChat?: unknown }).AgentryChat = { open: () => setOpen(true), close: () => setOpen(false) };
  }).catch(() => host.remove()); // chat disabled for this key: render nothing
})();
