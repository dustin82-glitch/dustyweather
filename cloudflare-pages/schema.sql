-- D1 schema using ESP payload field names.
CREATE TABLE IF NOT EXISTS readings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  station TEXT,
  device_id TEXT,
  sid TEXT,
  ts INTEGER NOT NULL,
  temp REAL,
  hum REAL,
  avg REAL,
  gust REAL,
  dir REAL,
  rain REAL,
  bat TEXT,
  battery_v REAL,
  temperature_c REAL,
  humidity REAL,
  pressure_hpa REAL,
  wind_kph REAL,
  wind_dir_deg REAL,
  rain_mm REAL
);

CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts DESC);
CREATE INDEX IF NOT EXISTS idx_readings_device_ts ON readings(device_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_readings_station_ts ON readings(station, ts DESC);
