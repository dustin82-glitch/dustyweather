export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    const cors = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type,X-Device-Token,Authorization"
    };

    const noCache = {
      "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
      "Pragma": "no-cache",
      "Expires": "0"
    };

    const json = (data, status = 200) =>
      new Response(JSON.stringify(data), {
        status,
        headers: { ...cors, ...noCache, "Content-Type": "application/json" }
      });

    const getDb = () => {
      if (!env.DB || typeof env.DB.prepare !== "function") {
        return null;
      }
      return env.DB;
    };

    const toFinite = (v) => {
      if (v === null || v === undefined || v === "") {
        return null;
      }
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    };

    const toFiniteLoose = (v) => {
      if (v === null || v === undefined || v === "") {
        return null;
      }
      if (typeof v === "number") {
        return Number.isFinite(v) ? v : null;
      }
      const cleaned = String(v).replace(/[^0-9.+-]/g, "");
      if (!cleaned) {
        return null;
      }
      const n = Number(cleaned);
      return Number.isFinite(n) ? n : null;
    };

    const toBatText = (body) => {
      if (body.bat !== undefined && body.bat !== null && body.bat !== "") {
        return String(body.bat);
      }
      if (body.battery_ok !== undefined && body.battery_ok !== null) {
        return body.battery_ok ? "Yes" : "No";
      }
      const batteryV = toFinite(body.battery_v);
      if (batteryV !== null) {
        return `${batteryV.toFixed(2)}V`;
      }
      return null;
    };

    const mapRow = (row) => {
      if (!row) {
        return {};
      }

      return {
        id: row.id ?? null,
        station: row.station ?? ((row.sid ?? row.device_id) === "rgyc_beacon" ? "rgyc" : "jarvis"),
        sid: row.sid ?? row.device_id ?? null,
        bat: row.bat ?? null,
        temp: row.temp ?? row.temperature_c ?? null,
        hum: row.hum ?? row.humidity ?? null,
        avg: row.avg ?? row.wind_kph ?? null,
        gust: row.gust ?? null,
        dir: row.dir ?? row.wind_dir_deg ?? row.winddirection ?? null,
        rain: row.rain ?? row.rain_mm ?? null,
        ts: row.ts ?? null,
        device_id: row.device_id ?? row.sid ?? null
      };
    };

    if (request.method === "OPTIONS") {
      return new Response("", { status: 204, headers: cors });
    }

    if (url.pathname === "/api/ingest" && request.method === "POST") {
      const token = request.headers.get("X-Device-Token");
      if (token !== env.DEVICE_TOKEN) {
        return new Response("Unauthorized", { status: 401, headers: { ...cors, ...noCache } });
      }

      let body;
      try {
        body = await request.json();
      } catch {
        return new Response("Bad JSON", { status: 400, headers: { ...cors, ...noCache } });
      }

      const now = Math.floor(Date.now() / 1000);
      const ts = Number(body.ts || now);
      const deviceId = String(body.device_id ?? body.sid ?? "ws-01");

      // Knots-first schema from ESP payload.
      const sid = String(body.sid ?? deviceId);
      const bat = toBatText(body);
      const temp = toFinite(body.temp ?? body.temperature_c);
      const hum = toFinite(body.hum ?? body.humidity);
      const avg = toFinite(body.avg);
      const gust = toFinite(body.gust);
      const dir = toFinite(body.dir ?? body.wind_dir_deg);
      const rain = toFinite(body.rain ?? body.rain_mm);
      const batteryV = toFinite(body.battery_v);

      const db = getDb();
      if (!db) {
        return json({ ok: false, error: "DB binding missing" }, 500);
      }

      try {
        // Preferred schema uses ESP payload names directly.
        await db.prepare(
          "INSERT INTO readings (station, device_id, sid, ts, temp, hum, avg, gust, dir, rain, bat, battery_v) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        ).bind(
          "jarvis",
          deviceId,
          sid,
          ts,
          temp,
          hum,
          avg,
          gust,
          dir,
          rain,
          bat,
          batteryV
        ).run();
      } 
      catch {
        return json({ ok: false, error: "Database error" }, 500);
      }
    
      return json({ ok: true });
    }

    if (url.pathname === "/rgyc-wind" && request.method === "POST") {
      const authHeader = request.headers.get("Authorization") || "";
      const bearer = authHeader.startsWith("Bearer ") ? authHeader.slice(7) : null;
      const expectedToken = env.RGYC_TOKEN || env.DEVICE_TOKEN;

      if (!bearer || bearer !== expectedToken) {
        return new Response("Unauthorized", { status: 401, headers: { ...cors, ...noCache } });
      }

      let body;
      try {
        body = await request.json();
      } catch {
        return new Response("Bad JSON", { status: 400, headers: { ...cors, ...noCache } });
      }

      const nowTs = Math.floor(Date.now() / 1000);
      const parsedUtc = Date.parse(String(body.time_utc || ""));
      const ts = Number.isFinite(parsedUtc) ? Math.floor(parsedUtc / 1000) : nowTs;
      const deviceId = String(body.device_id ?? "rgyc-beacon");
      const sid = String(body.sid ?? body.source ?? "rgyc_beacon");

      const avg = toFiniteLoose(body.avg_kts ?? body.wind_speed_kts);
      const gust = toFiniteLoose(body.max_kts ?? body.gust_kts);
      const dir = toFiniteLoose(body.wind_dir);

      const db = getDb();
      if (!db) {
        return json({ ok: false, error: "DB binding missing" }, 500);
      }

      try {
        await db.prepare(
          "INSERT INTO readings (station, device_id, sid, ts, avg, gust, dir) VALUES (?, ?, ?, ?, ?, ?, ?)"
        ).bind(
          "rgyc",
          deviceId,
          sid,
          ts,
          avg,
          gust,
          dir
        ).run();
      } catch {
        return json({ ok: false, error: "Database error" }, 500);
      }

      return json({ ok: true, ts, sid });
    }

    if (url.pathname === "/api/latest" && request.method === "GET") {
      const db = getDb();
      if (!db) {
        return json({ ok: false, error: "DB binding missing" }, 500);
      }

      try {
        const row = await db.prepare(
          "SELECT * FROM readings WHERE COALESCE(station, CASE WHEN sid = 'rgyc_beacon' THEN 'rgyc' ELSE 'jarvis' END) = 'jarvis' ORDER BY ts DESC LIMIT 1"
        ).first();

        return json(mapRow(row));
      } catch {
        return json({ ok: false, error: "Database error" }, 500);
      }
    }

    if (url.pathname === "/api/history" && request.method === "GET") {
      const hours = Math.max(1, Math.min(168, Number(url.searchParams.get("hours") || 24)));
      const since = Math.floor(Date.now() / 1000) - hours * 3600;

      const db = getDb();
      if (!db) {
        return json({ ok: false, error: "DB binding missing" }, 500);
      }

      try {
        const result = await db.prepare(
          "SELECT * FROM readings WHERE ts >= ? AND COALESCE(station, CASE WHEN sid = 'rgyc_beacon' THEN 'rgyc' ELSE 'jarvis' END) = 'jarvis' ORDER BY ts ASC"
        ).bind(since).all();

        return json((result.results || []).map(mapRow));
      } catch {
        return json({ ok: false, error: "Database error" }, 500);
      }
    }

    if (url.pathname === "/api/rgyc/latest" && request.method === "GET") {
      const db = getDb();
      if (!db) {
        return json({ ok: false, error: "DB binding missing" }, 500);
      }

      try {
        const row = await db.prepare(
          "SELECT * FROM readings WHERE COALESCE(station, CASE WHEN sid = 'rgyc_beacon' THEN 'rgyc' ELSE 'jarvis' END) = 'rgyc' ORDER BY ts DESC LIMIT 1"
        ).first();

        return json(mapRow(row));
      } catch {
        return json({ ok: false, error: "Database error" }, 500);
      }
    } 

    if (url.pathname === "/api/rgyc/history" && request.method === "GET") {
      const hours = Math.max(1, Math.min(168, Number(url.searchParams.get("hours") || 24)));
      const since = Math.floor(Date.now() / 1000) - hours * 3600;

      const db = getDb();
      if (!db) {
        return json({ ok: false, error: "DB binding missing" }, 500);
      }

      try {
        const result = await db.prepare(
          "SELECT * FROM readings WHERE ts >= ? AND COALESCE(station, CASE WHEN sid = 'rgyc_beacon' THEN 'rgyc' ELSE 'jarvis' END) = 'rgyc' ORDER BY ts ASC"
        ).bind(since).all();

        return json((result.results || []).map(mapRow));
      } catch {
        return json({ ok: false, error: "Database error" }, 500);
      }
    }

    return new Response("Not found", { status: 404, headers: { ...cors, ...noCache } });
  }
};