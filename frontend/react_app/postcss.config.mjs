/** @type {import('postcss-load-config').Config} */
const config = {
  // Tailwind 4 ships its own PostCSS plugin and handles vendor prefixes.
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
