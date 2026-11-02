import path from "node:path";
import { fileURLToPath } from "node:url";
import createMDX from "@next/mdx";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// NOTE: Plugins must be passed as serializable string identifiers when running
// under Turbopack (which uses a worker pool). Use the upstream package names.
const withMDX = createMDX({
  extension: /\.mdx?$/,
  options: {
    remarkPlugins: [["remark-gfm"]],
    rehypePlugins: [["rehype-slug"]],
  },
});

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  pageExtensions: ["ts", "tsx", "md", "mdx"],
  turbopack: {
    root: path.resolve(__dirname, "../.."),
  },
};

export default withMDX(nextConfig);
