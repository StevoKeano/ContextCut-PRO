// ContextCut-Free — Cloudflare Worker landing page
// Deploy: npx wrangler deploy cloudflare_worker_free.js

const HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>ContextCut-Free — Local RAG Chat</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0F172A;color:#E2E8F0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;font-size:15px;display:flex;justify-content:center;min-height:100vh;padding:40px 20px}
.c{max-width:640px;width:100%}
.hdr{text-align:center;margin-bottom:40px}
.hdr h1{font-size:28px;font-weight:800;letter-spacing:-.5px}
.hdr .b{display:inline-block;font-size:11px;background:#10B981;color:#000;padding:2px 10px;border-radius:4px;font-weight:700;letter-spacing:.5px;vertical-align:middle;margin-left:6px}
.hdr p{color:#64748B;margin-top:8px;font-size:14px}
.card{background:#1E293B;border:1px solid #334155;border-radius:10px;padding:28px 32px;margin-bottom:16px}
.card h3{font-size:13px;font-weight:700;color:#10B981;text-transform:uppercase;letter-spacing:.5px;margin-bottom:16px}
.row{display:flex;gap:12px;margin-bottom:12px}
.row:last-child{margin-bottom:0}
.fld{flex:1}
.fld label{display:block;font-size:11px;color:#64748B;margin-bottom:4px;text-transform:uppercase;letter-spacing:.3px;font-weight:600}
.fld input,.fld select{width:100%;background:#0F172A;border:1px solid #334155;border-radius:6px;padding:8px 12px;color:#E2E8F0;font-size:13px;font-family:inherit;outline:none;transition:border .15s}
.fld input:focus,.fld select:focus{border-color:#10B981}
.install-section{margin-top:8px}
.install-section .cmd-wrap{background:#0F172A;border:1px solid #334155;border-radius:8px;padding:14px 16px;font-size:12px;font-family:'SF Mono','Consolas','Monaco',monospace;color:#94A3B8;word-break:break-all;line-height:1.6;position:relative;margin-top:12px}
.install-section .cmd-wrap .copy{position:absolute;top:8px;right:8px;background:#334155;border:none;color:#94A3B8;font-size:11px;padding:4px 10px;border-radius:4px;cursor:pointer;font-family:inherit;transition:all .15s}
.install-section .cmd-wrap .copy:hover{background:#10B981;color:#000}
.btn{background:#10B981;color:#000;border:none;border-radius:8px;padding:12px 28px;font-size:14px;font-weight:700;cursor:pointer;font-family:inherit;transition:background .15s;width:100%}
.btn:hover{background:#059669}
.btn:active{transform:scale(.98)}
.ftr{text-align:center;margin-top:32px;color:#64748B;font-size:13px}
.ftr a{color:#10B981;text-decoration:none;font-weight:600}
.ftr a:hover{text-decoration:underline}
.tagline{color:#475569;font-size:12px;margin-top:4px}
@media(max-width:480px){.card{padding:20px 16px}.row{flex-direction:column;gap:10px}}
</style>
</head>
<body>
<div class="c">
  <div class="hdr">
    <h1>ContextCut<span class="b">FREE</span></h1>
    <p>Local RAG chat with your files. One Python file, no Docker, no license, no API keys.</p>
  </div>

  <div class="card">
    <h3>Ollama Connection</h3>
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
  </div>

  <div class="card">
    <h3>Models</h3>
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
  </div>

  <div class="install-section">
    <button class="btn" id="installBtn">Copy Install Command</button>
    <div class="cmd-wrap" id="cmdWrap">
      <span id="cmdText">Loading...</span>
      <button class="copy" id="copyBtn">Copy</button>
    </div>
    <div class="tagline">Run the command in your terminal. Requires Python 3, Ollama, and the chat + embed models pulled.</div>
  </div>

  <div class="ftr">
    <a href="https://api.contextcut-pro.com" target="_blank">ContextCut-PRO →</a>
    &nbsp; Unlimited files, Qdrant vector DB, Docker deployment, starter knowledge templates, license management.
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
  const base='https://raw.githubusercontent.com/anomalco/contextcut-pro/main/install-free.sh';
  return 'curl -sSf ' + base + ' | bash -s -- --host ' + h + ' --port ' + p + ' --chat-model ' + cm + ' --embed-model ' + em + ' --ctx-limit ' + cl + ' --cc-port ' + cp;
}

function updateCmd(){
  document.getElementById('cmdText').textContent=genCmd();
}

document.querySelectorAll('input').forEach(el=>el.addEventListener('input',updateCmd));
updateCmd();

document.getElementById('installBtn').addEventListener('click',async function(){
  const cmd=genCmd();
  try{
    await navigator.clipboard.writeText(cmd);
    this.textContent='Copied!';
    setTimeout(()=>{this.textContent='Copy Install Command'},2000);
  }catch(e){
    document.getElementById('cmdText').textContent=cmd;
    this.textContent='Select command below';
    setTimeout(()=>{this.textContent='Copy Install Command'},2000);
  }
});

document.getElementById('copyBtn').addEventListener('click',async function(){
  const cmd=genCmd();
  try{
    await navigator.clipboard.writeText(cmd);
    this.textContent='Copied!';
    setTimeout(()=>{this.textContent='Copy'},2000);
  }catch(e){
    const r=window.getSelection().toString();
    if(!r){
      document.getElementById('cmdText').textContent=cmd;
      document.execCommand('selectAll');
    }
  }
});
</script>
</body>
</html>`;

export default {
  async fetch(req) {
    return new Response(HTML, {
      headers: {
        "Content-Type": "text/html;charset=utf-8",
        "Access-Control-Allow-Origin": "*"
      }
    });
  }
};
