// Main process is compiled by tsc (not webpack) — see package.json scripts.
// This config tells nextron to skip webpack compilation for the main process
// by pointing to a non-existent dir. The pre-compiled JS in app/ is used directly.
module.exports = {};
