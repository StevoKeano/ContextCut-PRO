const VALID_LICENSES = new Set([
  "CC-PRO-0001-TEST", // Add real keys here as you sell them
]);
const MAX_SEATS = 1;
const HEARTBEAT_TIMEOUT = 30 * 60 * 1000;
async function handleRequest(req) {
  const url = new URL(req.url);
  if (url.pathname === "/v1/license/validate" && req.method === "POST") {
    return await handleValidate(req);
  }
  if (url.pathname === "/v1/heartbeat" && req.method === "POST") {
    return await handleHeartbeat(req);
  }
  return new Response("Not found", { status: 404 });
}
async function handleValidate(req) {
  const body = await req.json();
  const { license_key, instance_id, fingerprint } = body;
  if (!VALID_LICENSES.has(license_key)) {
    return json(401, { valid: false, error: "Invalid license key" });
  }
  const key = `license:${license_key}`;
  const instances = (await LICENSE_KV.get(key, "json")) || {};
  const activeInstances = Object.keys(instances).filter((id) => {
    return Date.now() - instances[id].last_heartbeat < HEARTBEAT_TIMEOUT;
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
  await LICENSE_KV.put(key, JSON.stringify(instances));
  return json(200, {
    valid: true,
    license_type: "single",
    seats: MAX_SEATS,
    message: "License activated",
    activated_at: instances[instance_id].activated_at,
  });
}
async function handleHeartbeat(req) {
  const body = await req.json();
  const { license_key, instance_id } = body;
  if (!VALID_LICENSES.has(license_key)) {
    return json(401, { valid: false, error: "Invalid license key" });
  }
  const key = `license:${license_key}`;
  const instances = (await LICENSE_KV.get(key, "json")) || {};
  if (!instances[instance_id]) {
    return json(403, { valid: false, error: "Instance not registered" });
  }
  instances[instance_id].last_heartbeat = Date.now();
  await LICENSE_KV.put(key, JSON.stringify(instances));
  return json(200, { valid: true });
}
function json(status, data) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
export default { fetch: handleRequest };
