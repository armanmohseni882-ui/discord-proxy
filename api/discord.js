// api/discord.js — Vercel Edge Function (no deps)
// Verifies Discord signature. For slash commands: ACK (type 5) and forward to n8n.
// For autocomplete (type 4): forward to n8n, WAIT for its reply, and return it (type 8).

export const config = { runtime: 'edge' };

export default async function handler(req) {
  if (req.method !== 'POST') return new Response('OK', { status: 200 });

  const signature = req.headers.get('X-Signature-Ed25519');
  const timestamp = req.headers.get('X-Signature-Timestamp');
  const publicKey = process.env.DISCORD_PUBLIC_KEY;
  if (!signature || !timestamp || !publicKey) {
    return new Response('Missing signature', { status: 401 });
  }

  const bodyText = await req.text();

  // Verify Ed25519: verify(publicKey, signature, timestamp + body)
  const enc = new TextEncoder();
  const msg = enc.encode(timestamp + bodyText);
  const sig = hexToBytes(signature);
  const key = await crypto.subtle.importKey('raw', hexToBytes(publicKey), { name: 'Ed25519' }, false, ['verify']);
  const ok = await crypto.subtle.verify('Ed25519', key, sig, msg);
  if (!ok) return new Response('Bad signature', { status: 401 });

  const payload = JSON.parse(bodyText);

  // 1) PING -> PONG
  if (payload.type === 1) {
    return json({ type: 1 });
  }

  const n8nUrl = process.env.N8N_WEBHOOK_URL; // e.g. https://YOURSUBDOMAIN.n8n.cloud/webhook/discord-stats

  // 2) AUTOCOMPLETE -> forward to n8n and return its JSON (type 8) immediately
  if (payload.type === 4) {
    const r = await fetch(n8nUrl, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-app-id': process.env.APP_ID || '' },
      body: JSON.stringify(payload)
    });
    const text = await r.text(); // n8n Respond node returns JSON string
    return new Response(text, { headers: { 'content-type': 'application/json' }, status: 200 });
  }

  // 3) SLASH (and any others) -> send deferred ephemeral ACK, then forward to n8n in background
  const forward = fetch(n8nUrl, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-app-id': process.env.APP_ID || '' },
    body: JSON.stringify(payload)
  }).catch(() => {});
  // Don't await; respond to Discord now
  return json({ type: 5, data: { flags: 64 } });
}

function hexToBytes(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
  return out;
}
function json(obj) {
  return new Response(JSON.stringify(obj), { headers: { 'content-type': 'application/json' } });
}
