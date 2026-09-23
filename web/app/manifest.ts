import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Futbol Modelo",
    short_name: "Futbol Modelo",
    description: "Calibrated soccer predictions — every prediction locked before kickoff, graded either way.",
    start_url: "/",
    display: "standalone",
    background_color: "#09090b",
    theme_color: "#09090b",
    // SVG scales cleanly to any icon size a launcher asks for --
    // avoids needing separate 192/512 PNG exports.
    icons: [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml" }],
  };
}
