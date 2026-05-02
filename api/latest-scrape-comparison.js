const fs = require("fs");
const path = require("path");

function readComparisonReport() {
  const candidates = [
    path.join(
      __dirname,
      "..",
      "frontend",
      "listings_map",
      "data",
      "latest_scrape_comparison.json",
    ),
    path.join(
      process.cwd(),
      "output",
      "consolidated",
      "latest_scrape_comparison.json",
    ),
    path.join(
      process.cwd(),
      "frontend",
      "listings_map",
      "data",
      "latest_scrape_comparison.json",
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
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed;
      }
      errors.push(`${candidate} is not a JSON object`);
    } catch (error) {
      errors.push(`${candidate}: ${String(error && error.message ? error.message : error)}`);
    }
  }

  if (errors.length) {
    throw new Error(`No valid comparison report found. ${errors.join("; ")}`);
  }

  return {
    generated_at: "",
    run_timestamp: "",
    summary: {
      previous_total: 0,
      current_total: 0,
      added: 0,
      removed: 0,
      price_changed: 0,
      other_changed: 0,
    },
    added: [],
    removed: [],
    price_changed: [],
    other_changed: [],
  };
}

module.exports = (req, res) => {
  try {
    const payload = readComparisonReport();
    res.setHeader("Cache-Control", "no-store, max-age=0");
    res.status(200).json(payload);
  } catch (error) {
    res.status(500).json({
      error: "Failed to load latest scrape comparison.",
      detail: String(error && error.message ? error.message : error),
    });
  }
};
