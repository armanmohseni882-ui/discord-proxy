// api/discord.js — Vercel Edge Function (no deps)
// Verifies Discord signature, ACKs ephemerally, and forwards to your n8n webhook.

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

  // Discord PING → PONG
  if (payload.type === 1) return json({ type: 1 });

  // Send deferred ephemeral ACK immediately
  const ack = json({ type: 5, data: { flags: 64 } });

  // Forward to n8n in background (don’t block Discord)
  const n8nUrl = process.env.N8N_WEBHOOK_URL; // e.g. https://YOURSUBDOMAIN.n8n.cloud/webhook/discord-stats
  fetch(n8nUrl, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-app-id': process.env.APP_ID || '' },
    body: JSON.stringify(payload),
  }).catch(() => {});

  return ack;
}

function hexToBytes(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
  return out;
}
function json(obj) {
  return new Response(JSON.stringify(obj), { headers: { 'content-type': 'application/json' } });
}
