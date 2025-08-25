// api/discord.js — Edge function: verifies Discord, handles autocomplete with cached rosters,
// and forwards slash commands to n8n. No external deps.

export const config = { runtime: 'edge' };

// simple 24h in-memory cache (survives warm instances)
const CACHE = globalThis.ROSTER_CACHE ?? (globalThis.ROSTER_CACHE = {});
const TTL = 24 * 60 * 60 * 1000;

const BDL = {
  nba: 'https://api.balldontlie.io/v1',
  nfl: 'https://nfl.balldontlie.io/v1',
  mlb: 'https://mlb.balldontlie.io/v1',
};

export default async function handler(req) {
  if (req.method !== 'POST') return new Response('OK', { status: 200 });

  // ---- Discord signature verification ----
  const signature = req.headers.get('X-Signature-Ed25519');
  const timestamp = req.headers.get('X-Signature-Timestamp');
  const publicKey = process.env.DISCORD_PUBLIC_KEY;
  if (!signature || !timestamp || !publicKey) return new Response('Missing signature', { status: 401 });

  const bodyText = await req.text();
  const ok = await verify(publicKey, signature, timestamp + bodyText);
  if (!ok) return new Response('Bad signature', { status: 401 });

  const payload = JSON.parse(bodyText);

  // 1) PING -> PONG
  if (payload.type === 1) return json({ type: 1 });

  // 2) AUTOCOMPLETE -> return choices immediately (type 8)
  if (payload.type === 4) {
    const cmd = payload.data?.name || '';
    const sport = cmd.startsWith('nba') ? 'nba' : cmd.startsWith('nfl') ? 'nfl' : 'mlb';
    const focused = (payload.data?.options || []).find(o => o.focused && o.name === 'player');
    const q = (focused?.value || '').toLowerCase();

    const roster = await getRoster(sport);
    const list = q
      ? roster.filter(p => p.name.toLowerCase().includes(q) || p.team.toLowerCase().includes(q))
      : roster;

    const choices = list.slice(0, 25).map(p => ({
      name: `${p.name} • ${p.team}${p.position ? ` • ${p.position}` : ''}`,
      value: String(p.id),
    }));

    return json({ type: 8, data: { choices } });
  }

  // 3) Slash command -> deferred ephemeral ACK, then forward to n8n in background
  const n8nUrl = process.env.N8N_WEBHOOK_URL; // e.g. https://<yours>.n8n.cloud/webhook/discord-stats
  fetch(n8nUrl, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-app-id': process.env.APP_ID || '' },
    body: JSON.stringify(payload),
  }).catch(() => {});

  return json({ type: 5, data: { flags: 64 } });
}

// ---- helpers ----
async function getRoster(sport) {
  const now = Date.now();
  const hit = CACHE[sport];
  if (hit && hit.exp > now) return hit.data;

  // pull all active players with pagination
  const key = process.env.BDL_KEY;
  const base = BDL[sport];
  let page = 1;
  const per = 100;
  const out = [];

  while (true) {
    const url = `${base}/players?active=true&page=${page}&per_page=${per}`;
    const res = await fetch(url, { headers: { Authorization: key, 'x-api-key': key } });
    if (!res.ok) throw new Error(`Roster ${sport} ${res.status}`);
    const d = await res.json();

    const rows = (d.data || d || []);
    for (const p of rows) {
      const name = `${p.first_name ?? p.firstName ?? ''} ${p.last_name ?? p.lastName ?? ''}`.trim();
      const team = (p.team && (p.team.abbreviation || p.team.abbr || p.team.name)) || '';
      const pos = (p.position || p.pos || '').toUpperCase();
      out.push({ id: p.id, name, team, position: pos });
    }

    if (!d.meta || !d.meta.next_page) break;
    page++;
  }

  // NFL filter to skill positions only
  if (sport === 'nfl') {
    const allow = new Set(['QB', 'RB', 'WR', 'TE', 'FB']);
    for (let i = out.length - 1; i >= 0; i--) if (!allow.has(out[i].position)) out.splice(i, 1);
  }

  out.sort((a, b) => a.name.localeCompare(b.name));
  CACHE[sport] = { data: out, exp: now + TTL };
  return out;
}

async function verify(publicKeyHex, signatureHex, message) {
  const key = await crypto.subtle.importKey('raw', hexToBytes(publicKeyHex), { name: 'Ed25519' }, false, ['verify']);
  return crypto.subtle.verify('Ed25519', key, hexToBytes(signatureHex), new TextEncoder().encode(message));
}
function hexToBytes(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
  return out;
}
function json(obj) {
  return new Response(JSON.stringify(obj), { headers: { 'content-type': 'application/json' } });
}
