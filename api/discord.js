// api/discord.js  — Vercel Edge Function (no deps)
// - Verifies Discord signatures
// - AUTOCOMPLETE (type 4): returns choices immediately (type 8)
//   * Uses BDL search for speed + 24h cached rosters
// - SLASH commands (type 2): sends deferred ephemeral ACK and forwards payload to n8n

export const config = { runtime: 'edge' };

// ---- simple 24h in-memory cache for rosters ----
const CACHE = globalThis.ROSTER_CACHE ?? (globalThis.ROSTER_CACHE = {});
const TTL = 24 * 60 * 60 * 1000;

const BDL = {
  nba: 'https://api.balldontlie.io/v1',
  nfl: 'https://nfl.balldontlie.io/v1',
  mlb: 'https://mlb.balldontlie.io/v1',
};

export default async function handler(req) {
  if (req.method !== 'POST') return new Response('OK', { status: 200 });

  // --- verify Discord signature ---
  const signature = req.headers.get('X-Signature-Ed25519');
  const timestamp = req.headers.get('X-Signature-Timestamp');
  const publicKey = process.env.DISCORD_PUBLIC_KEY;

  if (!signature || !timestamp || !publicKey) {
    return new Response('Missing signature headers', { status: 401 });
  }

  const bodyText = await req.text();

  try {
    const ok = await verify(publicKey, signature, timestamp + bodyText);
    if (!ok) return new Response('Bad signature', { status: 401 });
  } catch {
    return new Response('Signature verify failed', { status: 401 });
  }

  const payload = JSON.parse(bodyText);

  // 1) PING -> PONG
  if (payload.type === 1) return json({ type: 1 });

  // 2) AUTOCOMPLETE -> return choices immediately (type 8)
  if (payload.type === 4) {
    try {
      const cmd = payload.data?.name || '';
      const sport = cmd.startsWith('nba') ? 'nba' : cmd.startsWith('nfl') ? 'nfl' : 'mlb';
      const focused = (payload.data?.options || []).find(o => o.focused && o.name === 'player');
      const qRaw = focused?.value ?? '';
      const q = String(qRaw).trim().toLowerCase();

      let players = [];
      if (q.length >= 2) {
        // FAST PATH: API search -> < 1s typical
        players = await searchPlayers(sport, q);
      } else {
        // No query yet: return first 25 from cached roster (if ready)
        const roster = await getRoster(sport).catch(() => []);
        players = roster.slice(0, 25);
      }

      const choices = players.slice(0, 25).map(p => ({
        name: `${p.name} • ${p.team}${p.position ? ` • ${p.position}` : ''}`,
        value: String(p.id),
      }));

      return json({ type: 8, data: { choices } });
    } catch (e) {
      console.error('autocomplete error', e);
      // Return an empty list so Discord UI stays responsive
      return json({ type: 8, data: { choices: [] } });
    }
  }

  // 3) Slash command (type 2) and others -> deferred ephemeral ACK, then forward to n8n
  const n8nUrl = process.env.N8N_WEBHOOK_URL;
  fetch(n8nUrl, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-app-id': process.env.APP_ID || '' },
    body: bodyText,
  }).catch(err => console.error('forward to n8n failed', err));

  return json({ type: 5, data: { flags: 64 } }); // deferred ephemeral
}

/* ---------------- helpers ---------------- */

async function getRoster(sport) {
  const now = Date.now();
  const hit = CACHE[sport];
  if (hit && hit.exp > now) return hit.data;

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
    const rows = d.data || d || [];

    for (const p of rows) {
      const name = `${p.first_name ?? p.firstName ?? ''} ${p.last_name ?? p.lastName ?? ''}`.trim();
      const team = (p.team && (p.team.abbreviation || p.team.abbr || p.team.name)) || '';
      const pos = (p.position || p.pos || '').toUpperCase();
      out.push({ id: p.id, name, team, position: pos });
    }
    if (!d.meta || !d.meta.next_page) break;
    page++;
  }

  if (sport === 'nfl') {
    const allow = new Set(['QB', 'RB', 'WR', 'TE', 'FB']);
    for (let i = out.length - 1; i >= 0; i--) if (!allow.has(out[i].position)) out.splice(i, 1);
  }

  out.sort((a, b) => a.name.localeCompare(b.name));
  CACHE[sport] = { data: out, exp: now + TTL };
  return out;
}

async function searchPlayers(sport, q) {
  const key = process.env.BDL_KEY;
  const base = BDL[sport];
  const url = `${base}/players?active=true&search=${encodeURIComponent(q)}&per_page=25`;
  const res = await fetch(url, { headers: { Authorization: key, 'x-api-key': key } });
  if (!res.ok) throw new Error(`Search ${sport} ${res.status}`);
  const d = await res.json();
  const rows = d.data || d || [];
  const list = rows.map(p => ({
    id: p.id,
    name: `${p.first_name ?? p.firstName ?? ''} ${p.last_name ?? p.lastName ?? ''}`.trim(),
    team: (p.team && (p.team.abbreviation || p.team.abbr || p.team.name)) || '',
    position: (p.position || p.pos || '').toUpperCase(),
  }));
  if (sport === 'nfl') {
    const allow = new Set(['QB', 'RB', 'WR', 'TE', 'FB']);
    return list.filter(p => allow.has(p.position));
  }
  return list;
}

async function verify(publicKeyHex, signatureHex, message) {
  const key = await crypto.subtle.importKey(
    'raw',
    hexToBytes(publicKeyHex),
    { name: 'Ed25519' },
    false,
    ['verify']
  );
  return crypto.subtle.verify(
    'Ed25519',
    key,
    hexToBytes(signatureHex),
    new TextEncoder().encode(message)
  );
}

function hexToBytes(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
  return out;
}

function json(obj) {
  return new Response(JSON.stringify(obj), { headers: { 'content-type': 'application/json' } });
}
