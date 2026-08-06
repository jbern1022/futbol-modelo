import type { MetadataRoute } from "next";

const BASE_URL = "https://futbol.josephbernal.com";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: BASE_URL, changeFrequency: "daily", priority: 1 },
    { url: `${BASE_URL}/track-record`, changeFrequency: "daily", priority: 0.8 },
    { url: `${BASE_URL}/how-it-works`, changeFrequency: "monthly", priority: 0.5 },
    { url: `${BASE_URL}/lessons-learned`, changeFrequency: "monthly", priority: 0.5 },
    { url: `${BASE_URL}/petey`, changeFrequency: "monthly", priority: 0.5 },
  ];
}
