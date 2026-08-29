import type { Metadata } from "next";
import "./globals.css";
import ThemeToggle from "./theme-toggle";
import AskPeteyDrawer from "./ask-petey-drawer";
import Footer from "./footer";

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
    <html lang="en" className="h-full antialiased">
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col font-sans">
        <header className="flex justify-end px-4 py-2">
          <ThemeToggle />
        </header>
        <AskPeteyDrawer />
        {children}
        <Footer />
      </body>
    </html>
  );
}
