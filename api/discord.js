// api/discord.js — Vercel Edge function (no deps)
// - Verifies Discord signatures
// - Provides fast AUTOCOMPLETE for NBA/NFL/MLB players (with 24h roster cache)
// - Forwards slash commands to n8n (awaits the forward), then returns a deferred ephemeral ACK

export const config = { runtime: 'edge' };

/* ------------------------ config ------------------------ */

const BDL = {
  nba: 'https://api.balldontlie.io/v1',
  nfl: 'https://api.balldontlie.io/nfl/v1',
  mlb: 'https://api.balldontlie.io/mlb/v1',
};
const TTL = 24 * 60 * 60 * 1000; // 24h cache for rosters

// in-memory cache survives within the same edge instance
const CACHE = globalThis.ROSTER_CACHE ?? (globalThis.ROSTER_CACHE = {});

/* ------------------------ handler ------------------------ */

export default async function handler(req) {
  if (req.method !== 'POST') return new Response('OK', { status: 200 });

  const signature = req.headers.get('X-Signature-Ed25519');
  const timestamp = req.headers.get('X-Signature-Timestamp');
  const publicKey = process.env.DISCORD_PUBLIC_KEY;

  const bodyText = await req.text();

  // Verify Discord signature
  if (!signature || !timestamp || !publicKey) {
    return new Response('Missing signature headers', { status: 401 });
  }
  const ok = await verify(publicKey, signature, timestamp + bodyText).catch(() => false);
  if (!ok) return new Response('Bad signature', { status: 401 });

  const payload = JSON.parse(bodyText);

  // 1) PING -> PONG
  if (payload.type === 1) return json({ type: 1 });

  // 2) AUTOCOMPLETE (type 4) -> return choices immediately
  if (payload.type === 4) {
    try {
      const cmd = payload.data?.name || '';
      const sport =
        cmd.startsWith('nba') ? 'nba' : cmd.startsWith('nfl') ? 'nfl' : 'mlb';

      // focused option "player"
      const focused = (payload.data?.options || []).find(
        (o) => o.focused && o.name === 'player'
      );
      const q = String(focused?.value ?? '').trim().toLowerCase();

      let players = [];
      if (q.length >= 2) {
        players = await searchPlayers(sport, q);
      } else {
        const roster = await getActiveRoster(sport).catch(() => []);
        players = roster.slice(0, 25);
      }

      const choices = players.slice(0, 25).map((p) => ({
        name: `${p.name} • ${p.team}${p.position ? ` • ${p.position}` : ''}`,
        value: String(p.id),
      }));

      return json({ type: 8, data: { choices } });
    } catch (e) {
      console.error('autocomplete error', e);
      return json({ type: 8, data: { choices: [] } });
    }
  }

  // 3) Slash command (type 2): forward to n8n first, then ACK
  try {
    const res = await fetch(process.env.N8N_WEBHOOK_URL, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-app-id': process.env.APP_ID || '',
        'x-source': 'vercel-proxy',
      },
      body: bodyText,
    });
    console.log('n8n forward status', res.status);
  } catch (e) {
    console.error('forward to n8n failed', e);
  }

  // Deferred ephemeral response
  return json({ type: 5, data: { flags: 64 } });
}

/* ------------------------ helpers ------------------------ */

// Fast search against active players
async function searchPlayers(sport, q) {
  const key = process.env.BDL_KEY;
  const base = BDL[sport];
  // Prefer active players endpoint so dropdown stays clean
  const url = `${base}/players/active?search=${encodeURIComponent(q)}&per_page=25`;
  const res = await fetch(url, {
    headers: { Authorization: key, 'x-api-key': key },
  });
  if (!res.ok) throw new Error(`Search ${sport} ${res.status}`);
  const d = await res.json();
  const rows = d.data || d || [];
  let list = rows.map((p) => ({
    id: p.id,
    name: `${p.first_name ?? p.firstName ?? ''} ${p.last_name ?? p.lastName ?? ''}`.trim(),
    team:
      (p.team && (p.team.abbreviation || p.team.abbr || p.team.display_name || p.team.name)) || '',
    position: (p.position_abbreviation || p.position || p.pos || '').toUpperCase(),
  }));
  if (sport === 'nfl') {
    const allow = new Set(['QB', 'RB', 'WR', 'TE', 'FB']);
    list = list.filter((p) => allow.has(p.position));
  }
  return list;
}

// Cached active roster (cursor pagination)
async function getActiveRoster(sport) {
  const now = Date.now();
  const hit = CACHE[sport];
  if (hit && hit.exp > now) return hit.data;

  const key = process.env.BDL_KEY;
  const base = BDL[sport];
  const out = [];
  let cursor;

  do {
    const url = `${base}/players/active?per_page=100${cursor ? `&cursor=${cursor}` : ''}`;
    const res = await fetch(url, {
      headers: { Authorization: key, 'x-api-key': key },
    });
    if (!res.ok) throw new Error(`Active roster ${sport} ${res.status}`);
    const d = await res.json();
    const rows = d.data || d || [];
    for (const p of rows) {
      out.push({
        id: p.id,
        name: `${p.first_name ?? p.firstName ?? ''} ${p.last_name ?? p.lastName ?? ''}`.trim(),
        team:
          (p.team && (p.team.abbreviation || p.team.abbr || p.team.display_name || p.team.name)) ||
          '',
        position: (p.position_abbreviation || p.position || p.pos || '').toUpperCase(),
      });
    }
    cursor = d.meta?.next_cursor;
  } while (cursor);

  if (sport === 'nfl') {
    const allow = new Set(['QB', 'RB', 'WR', 'TE', 'FB']);
    for (let i = out.length - 1; i >= 0; i--) if (!allow.has(out[i].position)) out.splice(i, 1);
  }

  out.sort((a, b) => a.name.localeCompare(b.name));
  CACHE[sport] = { data: out, exp: now + TTL };
  return out;
}

/* ------------------------ crypto + io ------------------------ */

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
  return new Response(JSON.stringify(obj), {
    headers: { 'content-type': 'application/json' },
  });
}
