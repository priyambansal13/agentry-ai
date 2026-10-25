"use strict";(()=>{(()=>{var B;let s=document.currentScript,y=s==null?void 0:s.dataset.key,M=((B=s==null?void 0:s.dataset.api)!=null?B:"").replace(/\/$/,""),S=(s==null?void 0:s.dataset.position)==="bottom-left"?"left":"right";if(!y||!M||document.getElementById("agentry-chat-root"))return;let w=`agentry:${y}`,p={get(){var e;try{return JSON.parse((e=localStorage.getItem(w))!=null?e:"null")}catch{return null}},set(e){try{e?localStorage.setItem(w,JSON.stringify(e)):localStorage.removeItem(w)}catch{}}};function N(e){let n=parseInt(e.replace("#","").padEnd(6,"0").slice(0,6),16),[t,o,g]=[n>>16&255,n>>8&255,n&255].map(m=>{let $=m/255;return $<=.03928?$/12.92:(($+.055)/1.055)**2.4});return .2126*t+.7152*o+.0722*g>.4?"#111111":"#ffffff"}let h=document.createElement("div");h.id="agentry-chat-root",document.body.appendChild(h);let H=h.attachShadow({mode:"open"}),I=document.createElement("style");I.textContent=`
    :host { all: initial; }
    * { box-sizing: border-box; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
    .wrap { --brand: #c9f24b; --on-brand: #111; --bg: #fff; --ink: #111; --muted: #6b6b66; --line: #e4e4dc; --bubble: #f3f3ee;
            position: fixed; bottom: 20px; ${S}: 20px; z-index: 2147483000; color: var(--ink); }
    @media (prefers-color-scheme: dark) { .wrap { --bg: #171812; --ink: #f4f4f0; --muted: #9a9a92; --line: #2c2d25; --bubble: #23241d; } }
    .launcher { width: 60px; height: 60px; border-radius: 50%; border: 2px solid #111; background: var(--brand); color: var(--on-brand);
                cursor: pointer; display: grid; place-items: center; box-shadow: 0 8px 24px rgb(0 0 0 / .18); transition: transform .15s; }
    .launcher:hover { transform: translateY(-2px); }
    .launcher svg { width: 28px; height: 28px; }
    .panel { position: absolute; bottom: 76px; ${S}: 0; width: 370px; height: min(580px, calc(100vh - 110px));
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
  `,H.appendChild(I);let d=document.createElement("div");d.className="wrap",d.innerHTML=`
    <div class="panel" role="dialog" aria-modal="false" aria-label="Chat">
      <header><div class="avatar" aria-hidden="true"></div><div class="who"><div class="name"></div><div class="sub"></div></div>
        <button type="button" class="restart" aria-label="Start a new conversation" title="New conversation">\u21BA</button>
        <button type="button" class="close" aria-label="Close chat">\xD7</button></header>
      <div class="log" aria-live="polite"></div>
      <form><label style="position:absolute;left:-9999px" for="agentry-input">Message</label>
        <textarea id="agentry-input" rows="1" placeholder="Type a message\u2026" maxlength="2000"></textarea>
        <button type="submit">Send</button></form>
      <div class="foot">AI assistant \xB7 powered by <a href="https://agentry.dev" target="_blank" rel="noopener">Agentry</a></div>
    </div>
    <button type="button" class="launcher" aria-label="Open chat" aria-expanded="false">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z"/></svg>
    </button>`,H.appendChild(d);let a=e=>d.querySelector(e),z=a(".panel"),k=a(".launcher"),r=a(".log"),O=a("form"),u=a("textarea"),A=a("form button"),i=null,E=!1,x=!1;function v(e){x||(x=!0,c({from:"agent",text:e}))}function c(e){var t;if(e.from==="human"){let o=document.createElement("div");o.className="who",o.textContent=`${e.by?`${e.by} \xB7 `:""}${(t=i==null?void 0:i.business)!=null?t:""} team`,r.appendChild(o)}let n=document.createElement("div");if(n.className=`msg ${e.from}`,n.textContent=e.text,r.appendChild(n),e.booking){let o=document.createElement("div");o.className="booking";let g=document.createElement("b");g.textContent=`\u2713 Booked: ${e.booking.service}`,o.append(g,document.createTextNode(`${e.booking.when} with ${e.booking.staff}`)),r.appendChild(o)}r.scrollTop=r.scrollHeight}function C(e){var n;if((n=r.querySelector(".typing"))==null||n.remove(),e){let t=document.createElement("div");t.className="typing",t.setAttribute("aria-label","typing"),t.innerHTML="<i></i><i></i><i></i>",r.appendChild(t),r.scrollTop=r.scrollHeight}}async function f(e,n){var o,g;let t=await fetch(`${M}/widget/${encodeURIComponent(y)}${e}`,{...n,headers:{"Content-Type":"application/json",...(o=n==null?void 0:n.headers)!=null?o:{}}});if(!t.ok){let m="Something went wrong. Please try again.";try{m=(g=(await t.json()).detail)!=null?g:m}catch{}throw Object.assign(new Error(m),{status:t.status})}return t.json()}async function P(){let e=p.get();if(e)return e;let n=await f("/conversations",{method:"POST"}),t={id:n.conversation_id,token:n.token};return p.set(t),v(n.greeting),t}async function D(){let e=p.get();if(!e)return void(i&&v(i.greeting));try{let n=await f(`/conversations/${e.id}?token=${e.token}`);x=!0,n.messages.forEach(t=>{t.id&&t.from==="human"&&T.add(t.id),c(t)}),n.status==="handed_off"&&L()}catch{p.set(null),i&&v(i.greeting)}}let T=new Set,l;function L(){l||(l=window.setInterval(async()=>{let e=p.get();if(!e)return window.clearInterval(l),void(l=void 0);try{let n=await f(`/conversations/${e.id}?token=${e.token}`);for(let t of n.messages)t.from==="human"&&t.id&&!T.has(t.id)&&(T.add(t.id),c(t));n.status!=="handed_off"&&(window.clearInterval(l),l=void 0)}catch{}},4e3))}async function _(e){if(!(E||!e.trim())){E=!0,A.disabled=!0,c({from:"visitor",text:e}),u.value="",C(!0);try{let n=await P(),t=await f(`/conversations/${n.id}/messages`,{method:"POST",body:JSON.stringify({token:n.token,text:e})});C(!1),t.reply?c({from:"agent",text:t.reply,booking:t.booking}):t.status==="handed_off"&&(c({from:"system",text:"A team member will reply here soon."}),L()),(t.status==="handed_off"||t.reply&&t.handed_off)&&L()}catch(n){C(!1),c({from:"system",text:n.message})}finally{E=!1,A.disabled=!1,u.focus()}}}function b(e){z.classList.toggle("open",e),d.classList.toggle("open",e),k.setAttribute("aria-expanded",String(e)),k.setAttribute("aria-label",e?"Close chat":"Open chat"),e&&u.focus()}k.addEventListener("click",()=>b(!z.classList.contains("open"))),a(".close").addEventListener("click",()=>b(!1)),a(".restart").addEventListener("click",()=>{p.set(null),l&&(window.clearInterval(l),l=void 0),r.textContent="",x=!1,i&&v(i.greeting)}),d.addEventListener("keydown",e=>{e.key==="Escape"&&b(!1)}),O.addEventListener("submit",e=>{e.preventDefault(),_(u.value)}),u.addEventListener("keydown",e=>{e.key==="Enter"&&!e.shiftKey&&(e.preventDefault(),_(u.value))}),f("").then(e=>{i=e;let n=/^#[0-9a-f]{3,8}$/i.test(e.color)?e.color:"#c9f24b";d.style.setProperty("--brand",n),d.style.setProperty("--on-brand",N(n)),a(".name").textContent=e.agent_name,a(".sub").textContent=`${e.business} \xB7 AI assistant`;let t=a(".avatar");if(e.logo&&/^https:\/\//.test(e.logo)){let o=document.createElement("img");o.src=e.logo,o.alt="",t.appendChild(o)}else t.textContent=e.agent_name.charAt(0);D(),window.AgentryChat={open:()=>b(!0),close:()=>b(!1)}}).catch(()=>h.remove())})();})();
