const HEARTBEAT_TIMEOUT = 30 * 60 * 1000;

async function uuidv4() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (crypto.getRandomValues(new Uint8Array(1))[0] & 15);
    return c === "x" ? r.toString(16) : ((r & 3) | 8).toString(16);
  });
}

async function handleWebhook(request, env) {
  const body = await request.formData();
  const eventType = body.get("event_type");
  const product = body.get("product_name");

  if (eventType !== "sale_completed" || !product || !product.includes("ContextCut")) {
    return json(200, { ok: true, skipped: true });
  }

  const email = body.get("email");
  const orderId = body.get("order_id");
  const maxSeats = 3;

  const existingCheck = await env.LICENSE_KV.get(`order:${orderId}`);
  if (existingCheck) return json(200, { ok: true, duplicate: true });

  const uuid = await uuidv4();
  const licenseKey = `CC-PRO-${uuid}`;
  const key = `license:${licenseKey}`;

  await env.LICENSE_KV.put(key, "{}");
  await env.LICENSE_KV.put(`order:${orderId}`, licenseKey);

  const installUrl = `https://contextcut-license.ppsel03.workers.dev/install/${licenseKey}`;

  if (env.RESEND_API_KEY && email) {
    await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: "ContextCut PRO <noreply@contextcut.com>",
        to: [email],
        subject: "Your ContextCut PRO License Key & Install Link",
        html: `
          <h2>Welcome to ContextCut PRO</h2>
          <p>Thank you for your purchase. Here is your license information:</p>
          <p><strong>License Key:</strong> <code>${licenseKey}</code></p>
          <p><strong>Concurrent Seats:</strong> ${maxSeats}</p>
          <h3>Quick Install (Recommended)</h3>
          <p>Run this single command in your terminal:</p>
          <pre><code>curl -fsSL "${installUrl}" | bash</code></pre>
          <h3>Manual Install</h3>
          <pre><code>curl -fsSL https://raw.githubusercontent.com/StevoKeano/ContextCut-PRO/main/install.sh | bash</code></pre>
          <p>When prompted, paste your license key: <code>${licenseKey}</code></p>
          <hr>
          <p>Need help? Reply to this email or check the <a href="https://github.com/StevoKeano/ContextCut-PRO">setup guide</a>.</p>
        `,
      }),
    });
  }

  return json(200, { ok: true, license_key: licenseKey, install_url: installUrl });
}

async function handleInstallLink(request, env, licenseKey) {
  const key = `license:${licenseKey}`;
  const data = await env.LICENSE_KV.get(key);

  if (data === null) {
    return new Response("Invalid or expired license key.", { status: 401 });
  }

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

  return new Response(installScript, {
    headers: { "Content-Type": "text/x-sh" },
  });
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

  const activeInstances = Object.keys(instances).filter(id => {
    return (Date.now() - instances[id].last_heartbeat) < HEARTBEAT_TIMEOUT;
  });

  if (!instances[instance_id] && activeInstances.length >= MAX_SEATS) {
    return json(403, {
      valid: false,
      error: `License limit reached: ${activeInstances.length}/${MAX_SEATS} active seats`,
    });
  }

  instances[instance_id] = {
    fingerprint,
    activated_at: new Date().toISOString(),
    last_heartbeat: Date.now(),
    hostname: fingerprint?.hostname || "unknown",
  };

  await env.LICENSE_KV.put(key, JSON.stringify(instances));

  return json(200, {
    valid: true,
    license_type: "single",
    seats: MAX_SEATS,
    message: "License activated",
    activated_at: instances[instance_id].activated_at,
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
  const { license_key, instance_id } = body;

  const key = `license:${license_key}`;
  const stored = await env.LICENSE_KV.get(key);

  if (stored === null) {
    return json(401, { valid: false, error: "Invalid license key" });
  }

  const instances = JSON.parse(stored);

  if (instances[instance_id]) {
    delete instances[instance_id];
    await env.LICENSE_KV.put(key, JSON.stringify(instances));
  }

  return json(200, { valid: true, message: "Seat released" });
}

async function handleReset(request, env) {
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
  }
};
