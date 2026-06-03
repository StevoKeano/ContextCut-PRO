// ContextCut-Free — Cloudflare Worker landing page
// Deploy: wrangler deploy cloudflare_worker_free.js --name contextcut-free --compatibility-date 2026-06-03

// Cloudflare Web Analytics token
const CF_ANALYTICS = "ce319497fad4420eb0aecb32c24c3c45"

const FOOTER_UTM = "utm_source=cloudflare&utm_medium=landing&utm_campaign=contextcut-free"

const HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ContextCut-Free — Local RAG Chat for Your Files</title>
<!-- Cloudflare Web Analytics -->
<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{"token": "${CF_ANALYTICS}"}'></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0b1120;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;font-size:15px;display:flex;justify-content:center;min-height:100vh;padding:0 20px}
.c{max-width:720px;width:100%;padding:48px 0 64px}
h1{font-size:32px;font-weight:800;letter-spacing:-.5px;text-align:center}
h1 .b{display:inline-block;font-size:11px;background:#10b981;color:#000;padding:2px 10px;border-radius:4px;font-weight:700;letter-spacing:.5px;vertical-align:middle;margin-left:6px}
.sub{color:#64748b;text-align:center;margin-top:8px;font-size:15px;max-width:520px;margin-left:auto;margin-right:auto;line-height:1.5}
.actions{display:flex;gap:12px;justify-content:center;margin-top:24px;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;gap:6px;background:#10b981;color:#000;border:none;border-radius:8px;padding:12px 24px;font-size:14px;font-weight:700;cursor:pointer;font-family:inherit;text-decoration:none;transition:background .15s}
.btn:hover{background:#059669}
.btn-outline{background:transparent;color:#10b981;border:1px solid #10b981}
.btn-outline:hover{background:#10b981;color:#000}
.btn-sm{padding:8px 16px;font-size:12px}
.section{margin-top:40px}
.section h2{font-size:18px;font-weight:700;color:#f1f5f9;margin-bottom:16px}
.section h2 .badge{display:inline-block;font-size:10px;background:#10b981;color:#000;padding:1px 8px;border-radius:3px;font-weight:700;vertical-align:middle;margin-left:6px}
.card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:28px 32px}
.card-sm{padding:20px 24px}
.green{color:#10b981}
.muted{color:#64748b}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.gap12{display:flex;flex-direction:column;gap:12px}
.row{display:flex;gap:12px;margin-bottom:12px;align-items:end}
.row:last-child{margin-bottom:0}
.fld{flex:1}
.fld label{display:block;font-size:11px;color:#64748b;margin-bottom:4px;text-transform:uppercase;letter-spacing:.3px;font-weight:600}
.fld input,.fld select{width:100%;background:#0f172a;border:1px solid #334155;border-radius:6px;padding:8px 12px;color:#e2e8f0;font-size:13px;font-family:inherit;outline:none;transition:border .15s}
.fld input:focus,.fld select:focus{border-color:#10b981}
.cmd-wrap{background:#0f172a;border:1px solid #334155;border-radius:8px;padding:14px 16px;font-size:12px;font-family:'SF Mono','Consolas','Monaco',monospace;color:#94a3b8;word-break:break-all;line-height:1.6;position:relative;margin-top:12px}
.cmd-wrap .copy{position:absolute;top:8px;right:8px;background:#334155;border:none;color:#94a3b8;font-size:11px;padding:4px 10px;border-radius:4px;cursor:pointer;font-family:inherit;transition:all .15s}
.cmd-wrap .copy:hover{background:#10b981;color:#000}
.tagline{color:#475569;font-size:12px;margin-top:4px;text-align:center}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #334155}
th{color:#64748b;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.3px}
td{color:#cbd5e1}
td:last-child{text-align:center}
tr:last-child td{border-bottom:none}
.check{color:#10b981;font-weight:700}
.cross{color:#64748b}
.pro{color:#f59e0b;font-weight:600;font-size:11px}
.ftr{text-align:center;margin-top:48px;color:#64748b;font-size:13px;line-height:1.8}
.ftr a{color:#10b981;text-decoration:none}
.ftr a:hover{text-decoration:underline}
.use-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:12px}
.use-card{background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:16px;text-align:center}
.use-card .icon{font-size:24px;margin-bottom:6px}
.use-card h4{font-size:13px;font-weight:600;color:#e2e8f0}
.use-card p{font-size:12px;color:#64748b;margin-top:4px;line-height:1.4}
.testim{background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:16px;font-size:13px;color:#94a3b8;line-height:1.5;font-style:italic}
.testim strong{color:#e2e8f0;font-style:normal}
@media(max-width:600px){.grid2{grid-template-columns:1fr}.use-grid{grid-template-columns:1fr}.row{flex-direction:column;gap:10px}.card{padding:20px 16px}}
</style>
</head>
<body>
<div class="c">
  <div class="section" style="text-align:center">
    <h1>ContextCut<span class="b">FREE</span></h1>
    <p class="sub">Drop-in RAG for any local LLM. One file, no Docker, no license, no API keys. FAISS + SQLite + DuckDuckGo — everything runs locally.</p>
    <div class="actions">
      <button class="btn" id="installBtn">Get Install Command</button>
      <a class="btn btn-outline" href="https://github.com/StevoKeano/ContextCut-PRO?${FOOTER_UTM}" target="_blank" rel="noopener">GitHub</a>
      <a class="btn btn-outline" href="https://api.contextcut-pro.com/promo?${FOOTER_UTM}" target="_blank" rel="noopener">PRO Version →</a>
    </div>
  </div>

  <div class="section">
    <h2>What people use it for</h2>
    <div class="use-grid">
      <div class="use-card">
        <div class="icon">📄</div>
        <h4>Legal Research</h4>
        <p>Chat with case law, statutes, and contract templates locally</p>
      </div>
      <div class="use-card">
        <div class="icon">🏥</div>
        <h4>Medical Reference</h4>
        <p>Query clinical guidelines, ethics codes, and research papers</p>
      </div>
      <div class="use-card">
        <div class="icon">💰</div>
        <h4>Tax &amp; Accounting</h4>
        <p>Search IRS code sections, deductions, and compliance rules</p>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>Feature comparison</h2>
    <div class="card card-sm">
      <table>
        <tr><th>Feature</th><th>Free</th><th></th><th>PRO</th></tr>
        <tr><td>Knowledge file limit</td><td><span class="check">50 files</span></td><td></td><td><span class="pro">Unlimited</span></td></tr>
        <tr><td>Vector database</td><td><span class="check">FAISS (local)</span></td><td></td><td><span class="pro">Qdrant (server-grade)</span></td></tr>
        <tr><td>Embedding backend</td><td><span class="check">Ollama only</span></td><td></td><td><span class="pro">Voyage AI + Ollama</span></td></tr>
        <tr><td>Web search</td><td><span class="check">DuckDuckGo</span></td><td></td><td><span class="pro">DuckDuckGo + API keys</span></td></tr>
        <tr><td>Session persistence</td><td><span class="check">SQLite</span></td><td></td><td><span class="pro">SQLite + searchable archive</span></td></tr>
        <tr><td>Real-time dashboard</td><td><span class="cross">—</span></td><td></td><td><span class="pro">Token analytics, per-request breakdown</span></td></tr>
        <tr><td>File watcher (auto-ingest)</td><td><span class="cross">—</span></td><td></td><td><span class="pro">on_created/on_moved/on_deleted</span></td></tr>
        <tr><td>Cloud provider support</td><td><span class="cross">Ollama only</span></td><td></td><td><span class="pro">OpenAI, OpenRouter, Anthropic, xAI, Custom</span></td></tr>
        <tr><td>Starter knowledge templates</td><td><span class="cross">—</span></td><td></td><td><span class="pro">60+ domain-specific .md files</span></td></tr>
        <tr><td>Install</td><td><span class="check">curl → bash</span></td><td></td><td><span class="pro">curl → bash + systemd</span></td></tr>
        <tr><td>Price</td><td><span class="check"><strong>Free</strong></span></td><td></td><td><span class="pro">$99.88 one-time</span></td></tr>
        <tr><td>License required</td><td><span class="cross">No</span></td><td></td><td><span class="pro">Yes</span></td></tr>
      </table>
    </div>
  </div>

  <div class="section">
    <h2>Try it now — 30 seconds</h2>
    <div class="card">
      <h3 style="font-size:13px;font-weight:700;color:#10b981;text-transform:uppercase;letter-spacing:.5px;margin-bottom:16px">Ollama Connection</h3>
      <div class="row">
        <div class="fld">
          <label>Host</label>
          <input id="host" value="localhost" placeholder="localhost">
        </div>
        <div class="fld">
          <label>Port</label>
          <input id="port" value="11434" placeholder="11434">
        </div>
      </div>
      <h3 style="font-size:13px;font-weight:700;color:#10b981;text-transform:uppercase;letter-spacing:.5px;margin-bottom:16px;margin-top:20px">Models</h3>
      <div class="row">
        <div class="fld">
          <label>Chat Model</label>
          <input id="chatModel" value="qwen2.5:7b" placeholder="qwen2.5:7b">
        </div>
        <div class="fld">
          <label>Embed Model</label>
          <input id="embedModel" value="nomic-embed-text" placeholder="nomic-embed-text">
        </div>
      </div>
      <div class="row">
        <div class="fld">
          <label>Context Limit</label>
          <input id="ctxLimit" value="32768" type="number" min="2048" placeholder="32768">
        </div>
        <div class="fld">
          <label>Dashboard Port</label>
          <input id="ccPort" value="18788" type="number" min="1024" max="65535" placeholder="18788">
        </div>
      </div>
      <div style="margin-top:20px">
        <button class="btn" id="installBtn2" style="width:100%">Copy Install Command</button>
        <div class="cmd-wrap" id="cmdWrap">
          <span id="cmdText">Loading...</span>
          <button class="copy" id="copyBtn">Copy</button>
        </div>
        <div class="tagline">Requires Python 3, Ollama with chat + embed models pulled. Run in any terminal.</div>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="testim">"ContextCut-Free is exactly what I needed — a dead-simple way to dump my markdown files into a local LLM without spinning up Docker or paying for API access. Installed in under a minute."<br><br><strong>— r/LocalLLaMA user</strong></div>
  </div>

  <div class="ftr">
    <a href="https://github.com/StevoKeano/ContextCut-PRO?${FOOTER_UTM}" target="_blank" rel="noopener">GitHub</a> &middot;
    <a href="https://api.contextcut-pro.com/promo?${FOOTER_UTM}" target="_blank" rel="noopener">ContextCut-PRO</a> &middot;
    <a href="https://github.com/StevoKeano/ContextCut-PRO/issues?${FOOTER_UTM}" target="_blank" rel="noopener">Report Issue</a>
    <br>
    Unlimited files, Qdrant vector DB, real-time dashboard, multi-provider, 60+ starter templates — <a href="https://api.contextcut-pro.com/promo?${FOOTER_UTM}">Upgrade to PRO</a>
  </div>
</div>

<script>
function genCmd(){
  const h=document.getElementById('host').value||'localhost';
  const p=document.getElementById('port').value||'11434';
  const cm=document.getElementById('chatModel').value||'qwen2.5:7b';
  const em=document.getElementById('embedModel').value||'nomic-embed-text';
  const cl=document.getElementById('ctxLimit').value||'32768';
  const cp=document.getElementById('ccPort').value||'18788';
  const base='https://raw.githubusercontent.com/StevoKeano/ContextCut-PRO/main/install-free.sh';
  return 'curl -sSf ' + base + ' | bash -s -- --host ' + h + ' --port ' + p + ' --chat-model ' + cm + ' --embed-model ' + em + ' --ctx-limit ' + cl + ' --cc-port ' + cp;
}

function updateCmd(){
  document.getElementById('cmdText').textContent=genCmd();
}

document.querySelectorAll('input').forEach(el=>el.addEventListener('input',updateCmd));
updateCmd();

function doCopy(){
  const cmd=genCmd();
  navigator.clipboard.writeText(cmd).then(()=>{
    document.getElementById('installBtn').textContent='Copied!';
    document.getElementById('installBtn2').textContent='Copied!';
    setTimeout(()=>{
      document.getElementById('installBtn').textContent='Get Install Command';
      document.getElementById('installBtn2').textContent='Copy Install Command';
    },2000);
  }).catch(()=>{
    document.getElementById('cmdText').textContent=cmd;
    document.getElementById('installBtn').textContent='Select command below';
    document.getElementById('installBtn2').textContent='Select command below';
    setTimeout(()=>{
      document.getElementById('installBtn').textContent='Get Install Command';
      document.getElementById('installBtn2').textContent='Copy Install Command';
    },2000);
  });
}

document.getElementById('installBtn').addEventListener('click',doCopy);
document.getElementById('installBtn2').addEventListener('click',doCopy);
document.getElementById('copyBtn').addEventListener('click',doCopy);
</script>
</body>
</html>`

export default {
  async fetch(req) {
    const url = new URL(req.url)
    if (url.pathname.startsWith("/api/")) {
      return new Response(JSON.stringify({ status: "ok", version: "free" }), {
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
      })
    }
    return new Response(HTML, {
      headers: {
        "Content-Type": "text/html;charset=utf-8",
        "Access-Control-Allow-Origin": "*"
      }
    })
  }
}
