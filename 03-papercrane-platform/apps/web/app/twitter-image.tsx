// Twitter / X card. Same visual as the OG image — Twitter's summary_large_image
// card expects 1200×630 as well, so we re-export the OG route's component.
// `runtime` must be declared inline (Next 16 cannot statically detect it
// when re-exported from another module).
export const runtime = "edge";
export { default, alt, size, contentType } from "./opengraph-image";
