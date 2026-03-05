module.exports = (req, res) => {
  const mapsApiKey =
    process.env.GOOGLE_MAPS_BROWSER_API_KEY ||
    process.env.GOOGLE_MAPS_API_KEY ||
    "";

  res.setHeader("Cache-Control", "no-store, max-age=0");
  res.status(200).json({ mapsApiKey });
};
