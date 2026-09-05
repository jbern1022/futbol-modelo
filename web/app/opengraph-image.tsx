import { ImageResponse } from "next/og";

export const alt = "Futbol Modelo — Calibrated Soccer Predictions";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: "#09090b",
          color: "#fafafa",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ fontSize: 80, fontWeight: 700 }}>Futbol Modelo</div>
        <div style={{ fontSize: 32, marginTop: 24, color: "#a1a1aa" }}>
          Calibrated soccer predictions — MLS, Premier League, Serie A, La Liga
        </div>
        <div style={{ fontSize: 24, marginTop: 40, color: "#71717a" }}>
          Every prediction locked before kickoff. Graded either way.
        </div>
      </div>
    ),
    { ...size }
  );
}
