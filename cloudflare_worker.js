const HEARTBEAT_TIMEOUT = 30 * 60 * 1000;

async function uuidv4() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = crypto.getRandomValues(new Uint8Array(1))[0] & 15;
    return c === "x" ? r.toString(16) : ((r & 3) | 8).toString(16);
  });
}

async function handleWebhook(request, env) {
  const body = await request.formData();
  const eventType = body.get("resource_name");
  const product = body.get("product_name");

  if (
    eventType !== "sale" ||
    !product ||
    !product.includes("ContextCut")
  ) {
    return json(200, { ok: true, skipped: true });
  }

  const email = body.get("email");
  const orderId = body.get("order_number");
  const maxSeats = 3;

  const existingCheck = await env.LICENSE_KV.get(`order:${orderId}`);
  if (existingCheck) return json(200, { ok: true, duplicate: true });

  const uuid = await uuidv4();
  const licenseKey = `CC-PRO-${uuid}`;
  const key = `license:${licenseKey}`;

  await env.LICENSE_KV.put(key, "{}");
  await env.LICENSE_KV.put(`order:${orderId}`, licenseKey);

  const installUrl = `https://api.contextcut-pro.com/install/${licenseKey}`;
  console.log("Webhook fields:", JSON.stringify({ email, orderId, eventType, product }));

  if (env.RESEND_API_KEY && email) {
    const resendRes = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: "ContextCut PRO <noreply@contextcut.thehangarsatspicewood.com>",
        to: [email],
        subject: "Your ContextCut PRO License Key & Install Link",
        html: `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Welcome to ContextCut PRO</title>
</head>
<body style="margin:0;padding:0;background:#F8FAFC;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F8FAFC;padding:40px 0;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;">

  <tr><td style="background:#0F172A;border-radius:12px 12px 0 0;padding:32px 36px 24px;">
    <p style="margin:0 0 10px;font-size:11px;font-weight:700;letter-spacing:3px;color:#0EA5E9;text-transform:uppercase;">ContextCut PRO</p>
    <h1 style="margin:0;font-size:24px;font-weight:700;color:#F8FAFC;line-height:1.3;">Your AI privacy layer<br>is ready to install.</h1>
  </td></tr>

  <tr><td style="background:#FFFFFF;padding:32px 36px;">
    <p style="margin:0 0 20px;font-size:15px;color:#334155;line-height:1.7;">
      Thank you for your purchase. ContextCut PRO sits silently between your AI tools and your local LLM &mdash;
      injecting only what matters, keeping everything on your machine.
    </p>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px;">
    <tr><td style="background:#F1F5F9;border:1px solid #E2E8F0;border-radius:8px;padding:18px 22px;">
      <p style="margin:0 0 4px;font-size:10px;font-weight:700;letter-spacing:2px;color:#64748B;text-transform:uppercase;">Your License Key</p>
      <p style="margin:0 0 8px;font-size:13px;font-family:'Courier New',monospace;color:#0F172A;word-break:break-all;">${licenseKey}</p>
      <p style="margin:0;font-size:12px;color:#94A3B8;">${maxSeats} concurrent seats &nbsp;&middot;&nbsp; Lifetime license &nbsp;&middot;&nbsp; Keep this email</p>
    </td></tr>
    </table>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px;">
    <tr><td align="center">
      <a href="${installUrl}"
         style="display:inline-block;background:#0EA5E9;color:#FFFFFF;font-size:15px;font-weight:700;text-decoration:none;padding:15px 36px;border-radius:8px;">
        Get Started &rarr;
      </a>
      <p style="margin:10px 0 0;font-size:12px;color:#94A3B8;">Opens your personal install page &nbsp;&middot;&nbsp; No account needed</p>
    </td></tr>
    </table>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px;">
    <tr><td style="border-left:3px solid #0EA5E9;padding:4px 0 4px 18px;">
      <p style="margin:0 0 4px;font-size:11px;font-weight:700;letter-spacing:1px;color:#94A3B8;text-transform:uppercase;">What happens when you click</p>
      <p style="margin:0 0 6px;font-size:14px;color:#334155;line-height:1.7;"><span style="color:#0EA5E9;font-weight:700;">1&nbsp;</span> Your install page opens in the browser</p>
      <p style="margin:0 0 6px;font-size:14px;color:#334155;line-height:1.7;"><span style="color:#0EA5E9;font-weight:700;">2&nbsp;</span> Choose macOS or Linux &mdash; one command installs everything</p>
      <p style="margin:0 0 6px;font-size:14px;color:#334155;line-height:1.7;"><span style="color:#0EA5E9;font-weight:700;">3&nbsp;</span> Answer a few prompts (Ollama address, ports &mdash; defaults work)</p>
      <p style="margin:0;font-size:14px;color:#334155;line-height:1.7;"><span style="color:#0EA5E9;font-weight:700;">4&nbsp;</span> Dashboard opens at <span style="font-family:monospace;color:#0EA5E9;">http://localhost:18787</span></p>
    </td></tr>
    </table>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px;">
    <tr><td style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:8px;padding:14px 18px;">
      <p style="margin:0;font-size:13px;color:#166534;line-height:1.6;">
        <strong>100% local.</strong> Your documents, queries, and AI responses never leave your machine.
        No cloud. No telemetry. No subscriptions.
      </p>
    </td></tr>
    </table>

    <p style="margin:0;font-size:14px;color:#334155;line-height:1.7;">
      Questions? Just reply to this email &mdash; you will reach a human.
    </p>
  </td></tr>

  <tr><td style="background:#F8FAFC;border:1px solid #E2E8F0;border-top:none;border-radius:0 0 12px 12px;padding:18px 36px;">
    <p style="margin:0 0 4px;font-size:11px;font-weight:700;letter-spacing:1px;color:#94A3B8;text-transform:uppercase;">Technical reference</p>
    <p style="margin:0 0 4px;font-size:12px;color:#94A3B8;font-family:monospace;word-break:break-all;">Install URL: ${installUrl}</p>
    <p style="margin:0;font-size:12px;color:#94A3B8;">Docs: <a href="https://github.com/StevoKeano/ContextCut-PRO" style="color:#0EA5E9;">github.com/StevoKeano/ContextCut-PRO</a></p>
  </td></tr>

  <tr><td style="padding:20px 36px 0;">
    <p style="margin:0;font-size:12px;color:#94A3B8;text-align:center;line-height:1.6;">
      ContextCut PRO &nbsp;&middot;&nbsp; One-time purchase &nbsp;&middot;&nbsp; ${maxSeats} seats<br>
      <a href="mailto:stevekean@gmail.com" style="color:#94A3B8;">stevekean@gmail.com</a>
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>`,
      }),
    });
    const resendBody = await resendRes.json();
    console.log("Resend response:", resendRes.status, JSON.stringify(resendBody));
  }

  return json(200, {
    ok: true,
    license_key: licenseKey,
    install_url: installUrl,
  });
}

async function handleInstallLink(request, env, licenseKey) {
  const key = `license:${licenseKey}`;
  const data = await env.LICENSE_KV.get(key);

  if (data === null) {
    return new Response("Invalid or expired license key.", { status: 401 });
  }

  const ua = request.headers.get("User-Agent") || "";
  const isBrowser = ua.includes("Mozilla") || ua.includes("Chrome") || ua.includes("Safari");

  const installUrl = `https://api.contextcut-pro.com/install/${licenseKey}`;

  const installScript = `#!/bin/bash
set -e
export CONTEXTCUT_LICENSE_KEY="${licenseKey}"
SCRIPT_URL="https://raw.githubusercontent.com/StevoKeano/ContextCut-PRO/main/install.sh"
echo "  Downloading ContextCut PRO installer..."
curl -fsSL "$SCRIPT_URL" -o /tmp/contextcut-install.sh
chmod +x /tmp/contextcut-install.sh
echo "  Running installer with your license key pre-loaded..."
bash /tmp/contextcut-install.sh
rm -f /tmp/contextcut-install.sh
`;

  if (!isBrowser) {
    return new Response(installScript, { headers: { "Content-Type": "text/x-sh" } });
  }

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Install ContextCut PRO</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0F172A;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
.card{background:#1E293B;border:1px solid #334155;border-radius:16px;max-width:680px;width:100%;overflow:hidden}
.hdr{background:#0EA5E9;padding:28px 36px}
.hdr h1{color:#fff;font-size:22px;font-weight:700;margin-bottom:4px}
.hdr p{color:#E0F2FE;font-size:14px}
.bdy{padding:32px 36px}
.key-box{background:#0F172A;border:1px solid #334155;border-radius:8px;padding:14px 20px;margin-bottom:24px}
.kl{font-size:10px;font-weight:700;letter-spacing:2px;color:#64748B;text-transform:uppercase;margin-bottom:4px}
.kv{font-family:'Courier New',monospace;font-size:13px;color:#7DD3FC;word-break:break-all}
.steps{border-left:3px solid #0EA5E9;padding:4px 0 4px 20px;margin-bottom:24px}
.step{font-size:14px;color:#CBD5E1;line-height:1.8;margin-bottom:4px}
.step b{color:#0EA5E9}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px}
.fg{display:flex;flex-direction:column;gap:4px}
.fg.full{grid-column:1/-1}
.fg label{font-size:11px;font-weight:600;color:#64748B;text-transform:uppercase;letter-spacing:1px}
.fg input{background:#0F172A;border:1px solid #334155;border-radius:6px;padding:10px 12px;color:#E2E8F0;font-size:13px;font-family:'Courier New',monospace;outline:none;transition:border-color .15s}
.fg input:focus{border-color:#0EA5E9}
.fg input::placeholder{color:#475569}
.fg .hint{font-size:10px;color:#475569;margin-top:2px}
.gen-btn{background:#0EA5E9;color:#fff;border:none;border-radius:8px;padding:14px 24px;font-size:15px;font-weight:700;cursor:pointer;width:100%;transition:background .15s;margin-bottom:8px}
.gen-btn:hover{background:#0284C7}
.gen-btn:disabled{opacity:.5;cursor:default}
.term-box{background:#0F172A;border:1px solid #334155;border-radius:10px;overflow:hidden;margin-bottom:24px;display:none}
.term-hdr{background:#1E293B;padding:10px 16px;display:flex;align-items:center;gap:8px;border-bottom:1px solid #334155}
.term-dot{width:10px;height:10px;border-radius:50%}
.term-dot.r{background:#EF4444}
.term-dot.y{background:#EAB308}
.term-dot.g{background:#22C55E}
.term-title{font-size:12px;color:#64748B;flex:1}
.term-body{padding:16px 20px;position:relative}
.term-prompt{font-size:11px;color:#475569;margin-bottom:8px}
.term-cmd{font-family:'Courier New',monospace;font-size:13px;color:#7DD3FC;word-break:break-all;line-height:1.7;padding-right:80px;white-space:pre-wrap}
.term-copy{position:absolute;bottom:16px;right:20px;background:#1E293B;border:1px solid #334155;border-radius:6px;color:#94A3B8;font-size:12px;padding:6px 14px;cursor:pointer;transition:all .15s}
.term-copy:hover{background:#334155;color:#fff}
.term-copy.ok{background:#22C55E;border-color:#22C55E;color:#fff}
.priv{background:#0F172A;border:1px solid #1E3A2E;border-radius:8px;padding:14px 18px;margin-bottom:24px}
.priv p{font-size:13px;color:#4ADE80;line-height:1.6}
.foot{font-size:13px;color:#64748B;text-align:center}
.foot a{color:#0EA5E9;text-decoration:none}
@media(max-width:560px){.form-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="card">
  <div class="hdr">
    <h1>Install ContextCut PRO</h1>
    <p>Your license is verified &mdash; configure your setup below.</p>
  </div>
  <div class="bdy">
    <div class="key-box">
      <div class="kl">Your License Key</div>
      <div class="kv">${licenseKey}</div>
    </div>
    <div class="steps">
      <div class="step"><b>1 &nbsp;</b>Configure settings below &mdash; defaults work for most setups</div>
      <div class="step"><b>2 &nbsp;</b>Click <strong>Generate Install Command</strong></div>
      <div class="step"><b>3 &nbsp;</b>Copy the command, paste into Terminal, press Enter</div>
      <div class="step"><b>4 &nbsp;</b>Dashboard opens at <code>http://localhost:18787</code></div>
    </div>

    <div class="form-grid">
      <div class="fg full">
        <label>Voyage AI API Key</label>
        <input type="text" id="f-voyage" placeholder="leave blank for local Ollama embedding">
        <span class="hint">Blank = 100% local with Ollama &nbsp;|&nbsp; Enter key = Voyage AI (cloud embeddings)</span>
      </div>
      <div class="fg" id="grp-model">
        <label>Embedding Model</label>
        <input type="text" id="f-model" value="nomic-embed-text" placeholder="nomic-embed-text">
        <span class="hint">Only used when Voyage is blank</span>
      </div>
      <div class="fg">
        <label>Ollama Host</label>
        <input type="text" id="f-ollama-host" value="192.168.1.101">
        <span class="hint">Your Ollama server address</span>
      </div>
      <div class="fg">
        <label>Ollama Port</label>
        <input type="text" id="f-ollama-port" value="11434">
        <span class="hint">Default: 11434</span>
      </div>
      <div class="fg">
        <label>Qdrant Host</label>
        <input type="text" id="f-qdrant-host" value="localhost">
        <span class="hint">Qdrant vector DB address</span>
      </div>
      <div class="fg">
        <label>Qdrant Port</label>
        <input type="text" id="f-qdrant-port" value="6333">
        <span class="hint">Default: 6333</span>
      </div>
      <div class="fg">
        <label>Proxy Port</label>
        <input type="text" id="f-proxy-port" value="18788">
      </div>
      <div class="fg">
        <label>Dashboard Port</label>
        <input type="text" id="f-dash-port" value="18787">
      </div>
      <div class="fg">
        <label>Context Limit</label>
        <input type="text" id="f-ctx" value="8192">
        <span class="hint">Max tokens per request</span>
      </div>
      <div class="fg">
        <label>Min Relevance Score</label>
        <input type="text" id="f-score" value="0.20">
        <span class="hint">0.0 – 1.0 &nbsp;|&nbsp; Lower = more results</span>
      </div>
    </div>

    <button class="gen-btn" id="genBtn" onclick="generate()">Generate Install Command</button>

    <div class="term-box" id="termBox">
      <div class="term-hdr">
        <span class="term-dot r"></span>
        <span class="term-dot y"></span>
        <span class="term-dot g"></span>
        <span class="term-title">Terminal &mdash; bash</span>
      </div>
      <div class="term-body">
        <div class="term-prompt">$ ▶</div>
        <div class="term-cmd" id="termCmd"></div>
        <button class="term-copy" id="copyBtn" onclick="copyCmd()">Copy</button>
      </div>
    </div>

    <div class="priv">
      <p><strong>100% local.</strong> Your documents and queries never leave your machine. No cloud, no telemetry, no subscriptions.</p>
    </div>
    <div class="foot">
      Need help? &nbsp;<a href="mailto:stevekean@gmail.com">Reply to your purchase email</a> &nbsp;&middot;&nbsp; <a href="https://github.com/StevoKeano/ContextCut-PRO">Documentation</a>
    </div>
  </div>
</div>
<script>
function esc(v){return v.replace(/"/g,'\\\\"').replace(/'/g,"\\\\'")}
function generate(){
  const voyage=document.getElementById('f-voyage').value;
  const model=document.getElementById('f-model').value||'nomic-embed-text';
  const ohost=document.getElementById('f-ollama-host').value||'localhost';
  const oport=document.getElementById('f-ollama-port').value||'11434';
  const qhost=document.getElementById('f-qdrant-host').value||'localhost';
  const qport=document.getElementById('f-qdrant-port').value||'6333';
  const pport=document.getElementById('f-proxy-port').value||'18788';
  const dport=document.getElementById('f-dash-port').value||'18787';
  const ctx=document.getElementById('f-ctx').value||'8192';
  const score=document.getElementById('f-score').value||'0.20';

  const lines=[
    'curl -fsSL "'+esc('${installUrl}')+'" -o /tmp/cc-install.sh \\\\',
    '  && VOYAGE_KEY="'+esc(voyage)+'" \\\\',
    '  EMBED_MODEL="'+esc(model)+'" \\\\',
    '  OLLAMA_HOST="'+esc(ohost)+'" \\\\',
    '  OLLAMA_PORT="'+esc(oport)+'" \\\\',
    '  QDRANT_HOST="'+esc(qhost)+'" \\\\',
    '  QDRANT_PORT="'+esc(qport)+'" \\\\',
    '  PROXY_PORT="'+esc(pport)+'" \\\\',
    '  DASH_PORT="'+esc(dport)+'" \\\\',
    '  CTX_LIMIT="'+esc(ctx)+'" \\\\',
    '  MIN_SCORE="'+esc(score)+'" \\\\',
    '  bash /tmp/cc-install.sh \\\\',
    '  && rm -f /tmp/cc-install.sh'
  ];
  document.getElementById('termCmd').textContent=lines.join('\\n');
  document.getElementById('termBox').style.display='';
  document.getElementById('genBtn').textContent='Generate Install Command';
  document.getElementById('genBtn').disabled=false;
}
function copyCmd(){
  const txt=document.getElementById('termCmd').textContent;
  navigator.clipboard.writeText(txt).then(()=>{
    const btn=document.getElementById('copyBtn');
    btn.textContent='Copied!';btn.classList.add('ok');
    setTimeout(()=>{btn.textContent='Copy';btn.classList.remove('ok');},2000);
  });
}
document.getElementById('f-voyage').addEventListener('input',function(){
  const grp=document.getElementById('grp-model');
  grp.style.opacity=this.value?'0.3':'1';
});
</script>
</body>
</html>`;

  return new Response(html, { headers: { "Content-Type": "text/html;charset=UTF-8" } });
}

async function handleValidate(request, env) {
  const body = await request.json();
  const { license_key, instance_id, fingerprint } = body;

  const key = `license:${license_key}`;
  const stored = await env.LICENSE_KV.get(key);

  if (stored === null) {
    return json(401, { valid: false, error: "Invalid license key" });
  }

  const instances = JSON.parse(stored);
  const MAX_SEATS = 3;

  const activeInstances = Object.keys(instances).filter((id) => {
    return Date.now() - instances[id].last_heartbeat < HEARTBEAT_TIMEOUT;
  });

  if (!instances[instance_id] && activeInstances.length >= MAX_SEATS) {
    return json(403, {
      valid: false,
      error: `License limit reached: ${activeInstances.length}/${MAX_SEATS} active seats`,
    });
  }

  const instance_secret = crypto.randomUUID();
  instances[instance_id] = {
    fingerprint,
    activated_at: new Date().toISOString(),
    last_heartbeat: Date.now(),
    hostname: fingerprint?.hostname || "unknown",
    instance_secret,
  };

  await env.LICENSE_KV.put(key, JSON.stringify(instances));

  return json(200, {
    valid: true,
    license_type: "single",
    seats: MAX_SEATS,
    message: "License activated",
    activated_at: instances[instance_id].activated_at,
    instance_secret,
  });
}

async function handleHeartbeat(request, env) {
  const body = await request.json();
  const { license_key, instance_id } = body;

  const key = `license:${license_key}`;
  const stored = await env.LICENSE_KV.get(key);

  if (stored === null) {
    return json(401, { valid: false, error: "Invalid license key" });
  }

  const instances = JSON.parse(stored);

  if (!instances[instance_id]) {
    return json(403, { valid: false, error: "Instance not registered" });
  }

  instances[instance_id].last_heartbeat = Date.now();
  await env.LICENSE_KV.put(key, JSON.stringify(instances));

  return json(200, { valid: true });
}

async function handleRelease(request, env) {
  const body = await request.json();
  const { license_key, instance_id, instance_secret } = body;

  if (!instance_secret) {
    return json(400, { valid: false, error: "instance_secret required" });
  }

  const key = `license:${license_key}`;
  const stored = await env.LICENSE_KV.get(key);

  if (stored === null) {
    return json(401, { valid: false, error: "Invalid license key" });
  }

  const instances = JSON.parse(stored);

  if (!instances[instance_id]) {
    return json(404, { valid: false, error: "Instance not found" });
  }

  if (instances[instance_id].instance_secret !== instance_secret) {
    return json(403, { valid: false, error: "Unauthorized" });
  }

  delete instances[instance_id];
  await env.LICENSE_KV.put(key, JSON.stringify(instances));

  return json(200, { valid: true, message: "Seat released" });
}

async function handleReset(request, env) {
  const adminSecret = request.headers.get("X-Admin-Secret");
  if (!adminSecret || adminSecret !== env.ADMIN_SECRET) {
    return json(401, { valid: false, error: "Unauthorized" });
  }
  const body = await request.json();
  const { license_key } = body;

  const key = `license:${license_key}`;
  const stored = await env.LICENSE_KV.get(key);

  if (stored === null) {
    return json(401, { valid: false, error: "Invalid license key" });
  }

  await env.LICENSE_KV.put(key, "{}");

  return json(200, { valid: true, message: "All seats reset" });
}

function json(status, data) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      try {
        await env.LICENSE_KV.get("health_check");
        return json(200, { status: "healthy", kv: "ok", uptime: "ok" });
      } catch (e) {
        return json(500, { status: "unhealthy", error: e.message });
      }
    }

    if (url.pathname === "/webhook/gumroad" && request.method === "POST") {
      return await handleWebhook(request, env);
    }

    const installMatch = url.pathname.match(/^\/install\/(CC-PRO-[a-f0-9-]+)$/);
    if (installMatch) {
      return await handleInstallLink(request, env, installMatch[1]);
    }

    if (url.pathname === "/v1/license/validate" && request.method === "POST") {
      return await handleValidate(request, env);
    }
    if (url.pathname === "/v1/heartbeat" && request.method === "POST") {
      return await handleHeartbeat(request, env);
    }
    if (url.pathname === "/v1/license/release" && request.method === "POST") {
      return await handleRelease(request, env);
    }
    if (url.pathname === "/v1/license/reset" && request.method === "POST") {
      return await handleReset(request, env);
    }

    return new Response("Not found", { status: 404 });
  },
};
