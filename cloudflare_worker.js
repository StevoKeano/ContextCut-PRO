const VALID_LICENSES = new Set([
  "CC-PRO-0001-TEST",
]);

const MAX_SEATS = 3;
const HEARTBEAT_TIMEOUT = 30 * 60 * 1000;

async function handleValidate(request, env) {
  const body = await request.json();
  const { license_key, instance_id, fingerprint } = body;

  if (!VALID_LICENSES.has(license_key)) {
    return json(401, { valid: false, error: "Invalid license key" });
  }

  const key = `license:${license_key}`;
  const instances = await env.LICENSE_KV.get(key, "json") || {};

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

  if (!VALID_LICENSES.has(license_key)) {
    return json(401, { valid: false, error: "Invalid license key" });
  }

  const key = `license:${license_key}`;
  const instances = await env.LICENSE_KV.get(key, "json") || {};

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

  if (!VALID_LICENSES.has(license_key)) {
    return json(401, { valid: false, error: "Invalid license key" });
  }

  const key = `license:${license_key}`;
  const instances = await env.LICENSE_KV.get(key, "json") || {};

  if (instances[instance_id]) {
    delete instances[instance_id];
    await env.LICENSE_KV.put(key, JSON.stringify(instances));
  }

  return json(200, { valid: true, message: "Seat released" });
}

async function handleReset(request, env) {
  const body = await request.json();
  const { license_key } = body;

  if (!VALID_LICENSES.has(license_key)) {
    return json(401, { valid: false, error: "Invalid license key" });
  }

  const key = `license:${license_key}`;
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
