/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: true,
  // Fully static export: every page is client-rendered against the backend
  // API, so no SSR is needed. This lets Amplify host it as a plain static
  // site (platform WEB), which sidesteps the WEB_COMPUTE service-role
  // assumption that has been failing account-side since 2026-07-21.
  output: "export",
  trailingSlash: true,   // deep links like /images/ resolve on static hosting
  // Optional sub-path hosting (e.g. Caddy serving at /app on the backend
  // host). Empty (default) keeps root-path behavior for Amplify/Vercel.
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || "",
};
