-- One-time migration for existing D1 databases.
-- Safe to run once after readings table already exists.

ALTER TABLE readings ADD COLUMN station TEXT;

UPDATE readings
SET station = CASE
  WHEN sid = 'rgyc_beacon' THEN 'rgyc'
  ELSE 'jarvis'
END
WHERE station IS NULL;

CREATE INDEX IF NOT EXISTS idx_readings_station_ts ON readings(station, ts DESC);
