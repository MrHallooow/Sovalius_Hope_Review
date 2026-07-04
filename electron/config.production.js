// Packaged-build defaults. The ONLY thing the desktop app needs to know is
// where the review gateway lives — database and object-storage credentials
// are the gateway's concern and never ship inside the app again.
//
// Override without rebuilding by placing a `.env` with GATEWAY_URL=... next
// to the installed app (resources/.env), or by setting the GATEWAY_URL
// environment variable.
module.exports = {
  GATEWAY_URL: "http://127.0.0.1:8090",
};
