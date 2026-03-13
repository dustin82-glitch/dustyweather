export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    const cors = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type,X-Device-Token"
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
          "INSERT INTO readings (device_id, sid, ts, temp, hum, avg, gust, dir, rain, bat, battery_v) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        ).bind(
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

    if (url.pathname === "/api/latest" && request.method === "GET") {
      const db = getDb();
      if (!db) {
        return json({ ok: false, error: "DB binding missing" }, 500);
      }

      try {
        const row = await db.prepare(
          "SELECT * FROM readings ORDER BY ts DESC LIMIT 1"
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
          "SELECT * FROM readings WHERE ts >= ? ORDER BY ts ASC"
        ).bind(since).all();

        return json((result.results || []).map(mapRow));
      } catch {
        return json({ ok: false, error: "Database error" }, 500);
      }
    }

    return new Response("Not found", { status: 404, headers: { ...cors, ...noCache } });
  }
};