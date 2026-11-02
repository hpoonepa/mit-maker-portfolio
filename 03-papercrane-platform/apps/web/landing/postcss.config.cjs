// Keep the standalone landing build isolated from apps/web's Tailwind
// PostCSS pipeline. The supplied site ships authored CSS and needs no plugins.
module.exports = { plugins: {} };
