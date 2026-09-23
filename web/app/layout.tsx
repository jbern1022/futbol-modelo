import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import ThemeToggle from "./theme-toggle";
import NavLinks from "./nav-links";
import AskPeteyDrawer from "./ask-petey-drawer";
import Footer from "./footer";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

const SITE_URL = "https://futbol.josephbernal.com";
const DESCRIPTION = "Calibrated soccer prediction system — live fixtures and prediction slates.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "Futbol Modelo",
  description: DESCRIPTION,
  alternates: {
    types: {
      "application/rss+xml": `${SITE_URL}/feed.xml`,
    },
  },
  openGraph: {
    title: "Futbol Modelo",
    description: DESCRIPTION,
    url: SITE_URL,
    siteName: "Futbol Modelo",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Futbol Modelo",
    description: DESCRIPTION,
  },
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "Futbol Modelo",
    statusBarStyle: "black-translucent",
  },
};

// viewport-fit=cover + theme-color let a standalone-mode PWA (added to
// home screen) draw behind the iOS notch/status bar and tint the
// status bar to match the site's dark background, instead of the
// default white bar every other unconfigured site gets.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fafafa" },
    { media: "(prefers-color-scheme: dark)", color: "#09090b" },
  ],
};

const THEME_INIT_SCRIPT = `
(function() {
  try {
    var stored = localStorage.getItem('theme');
    var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    var dark = stored ? stored === 'dark' : prefersDark;
    if (dark) document.documentElement.classList.add('dark');
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`h-full antialiased ${geistSans.variable} ${geistMono.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col font-sans">
        <header className="flex items-center justify-between px-4 py-2 border-b border-zinc-100 dark:border-zinc-800">
          <NavLinks />
          <ThemeToggle />
        </header>
        <AskPeteyDrawer />
        {children}
        <Footer />
      </body>
    </html>
  );
}
