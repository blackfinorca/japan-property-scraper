const fs = require("fs");
const path = require("path");

function readPayload() {
  const candidates = [
    path.join(
      __dirname,
      "..",
      "frontend",
      "listings_map",
      "data",
      "listings_map_payload.json",
    ),
    path.join(
      process.cwd(),
      "output",
      "consolidated",
      "listings_map_payload.json",
    ),
    path.join(
      process.cwd(),
      "frontend",
      "listings_map",
      "data",
      "listings_map_payload.json",
    ),
  ];
  const errors = [];

  for (const candidate of candidates) {
    if (!fs.existsSync(candidate)) {
      continue;
    }

    try {
      const raw = fs.readFileSync(candidate, "utf-8");
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return parsed;
      }
      errors.push(`${candidate} is not a JSON array`);
    } catch (error) {
      errors.push(`${candidate}: ${String(error && error.message ? error.message : error)}`);
    }
  }

  if (errors.length) {
    throw new Error(`No valid map payload file found. ${errors.join("; ")}`);
  }

  return [];
}

module.exports = (req, res) => {
  try {
    const payload = readPayload();
    res.setHeader("Cache-Control", "no-store, max-age=0");
    res.status(200).json(payload);
  } catch (error) {
    res.status(500).json({
      error: "Failed to load listings map payload.",
      detail: String(error && error.message ? error.message : error),
    });
  }
};
