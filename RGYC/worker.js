export default {
  /**
   * @param {Request} request
   * @param {Env} env
   * @param {ExecutionContext} ctx
   */
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    //
    // GET /health  -> quick DB check
    //
    if (request.method === "GET" && url.pathname === "/health") {
      try {
        await env.DB.prepare("SELECT 1").first();
        return jsonResponse({ status: "ok" });
      } catch (err) {
        console.error("Health check failed:", err);
        return jsonResponse({ error: "db_error" }, 500);
      }
    }

    //
    // GET /api/latest  -> latest reading from D1
    //
    if (request.method === "GET" && url.pathname === "/api/latest") {
      try {
        const row = await env.DB.prepare(
          `
          SELECT *
          FROM readings
          WHERE ts_utc IS NOT NULL
          ORDER BY ts_utc DESC
          LIMIT 1
          `
        ).first();

        if (!row) {
          return jsonResponse({ error: "no_data" }, 404);
        }

        return jsonResponse({ status: "ok", latest: row });
      } catch (err) {
        console.error("Error fetching latest reading:", err);
        return jsonResponse({ error: "db_query_failed" }, 500);
      }
    }

    //
    // POST /rgyc-wind  -> ingest endpoint
    //
    if (url.pathname !== "/rgyc-wind") {
      // Any other path: 404
      return jsonResponse({ error: "not_found" }, 404);
    }

    if (request.method !== "POST") {
      // We only accept POST on /rgyc-wind
      return new Response("Method Not Allowed", {
        status: 405,
        headers: { Allow: "POST" },
      });
    }

    // Simple shared-secret auth
    const expectedSecret = env.INGEST_SHARED_SECRET;
    if (expectedSecret) {
      const authHeader = request.headers.get("Authorization") || "";
      const token = authHeader.startsWith("Bearer ")
        ? authHeader.slice("Bearer ".length)
        : null;
      if (!token || token !== expectedSecret) {
        return jsonResponse({ error: "unauthorized" }, 401);
      }
    }

    let body;
    try {
      body = await request.json();
    } catch (err) {
      return jsonResponse({ error: "invalid_json" }, 400);
    }

    // Validate required fields
    const required = [
      "source",
      "time_local",
      "time_utc",
      "wind_speed_kts",
      "wind_dir",
      "image_url",
    ];
    for (const field of required) {
      if (body[field] === undefined || body[field] === null) {
        return jsonResponse({ error: `missing_field:${field}` }, 400);
      }
    }

    const source = String(body.source);
    const timeLocal = String(body.time_local); // kept for potential logging / future use
    const timeUtcRaw = String(body.time_utc);
    const imageUrl = String(body.image_url);

    // Normalize UTC timestamp (we'll trust it's valid ISO-ish; D1 stores as TEXT)
    const tsUtc = timeUtcRaw;

    // Numeric parsing helpers
    const parseNumberOrNull = (val) => {
      if (val === undefined || val === null || val === "") return null;
      const n =
        typeof val === "number"
          ? val
          : parseFloat(String(val).replace(",", "."));
      return Number.isFinite(n) ? n : null;
    };

    // Wind speed
    const windSpeedKts = parseNumberOrNull(body.wind_speed_kts);

    // Wind direction: we want a float degrees and preserve raw
    const windDirRaw = String(body.wind_dir);
    let windDirDeg = null;
    {
      const cleaned = windDirRaw.replace(/[^0-9.+-]/g, "");
      const n = parseFloat(cleaned);
      if (Number.isFinite(n)) {
        windDirDeg = n;
      }
    }

    const maxKts = parseNumberOrNull(body.max_kts);
    const minKts = parseNumberOrNull(body.min_kts);
    const avgKts = parseNumberOrNull(body.avg_kts);

    // Insert into D1
    const sql = `
      INSERT INTO readings (
        ts_utc,
        source,
        wind_speed_kts,
        wind_dir_deg,
        wind_dir_raw,
        max_kts,
        min_kts,
        avg_kts,
        image_url
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `;

    try {
      const stmt = env.DB.prepare(sql).bind(
        tsUtc,
        source,
        windSpeedKts,
        windDirDeg,
        windDirRaw,
        maxKts,
        minKts,
        avgKts,
        imageUrl
      );

      const result = await stmt.run();
      const insertedId = result.meta?.last_row_id ?? null;

      return jsonResponse({
        status: "ok",
        inserted_id: insertedId,
        ts_utc: tsUtc,
        source,
      });
    } catch (err) {
      console.error("D1 insert error:", err);
      return jsonResponse({ error: "db_insert_failed" }, 500);
    }
  },
};

/**
 * Helper to return JSON Response.
 */
function jsonResponse(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json",
    },
  });
}

/**
 * @typedef {Object} Env
 * @property {D1Database} DB
 * @property {string} [INGEST_SHARED_SECRET]
 */