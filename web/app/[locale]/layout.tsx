import type { Metadata, Viewport } from "next";
import { notFound } from "next/navigation";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Geist, Geist_Mono } from "next/font/google";
import "../globals.css";
import { routing } from "@/i18n/routing";
import ThemeToggle from "./theme-toggle";
import NavLinks from "./nav-links";
import LocaleSwitcher from "./locale-switcher";
import AskPeteyDrawer from "./ask-petey-drawer";
import Footer from "./footer";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

const SITE_URL = "https://futbol.josephbernal.com";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Meta" });
  const title = t("title");
  const description = t("description");
  // localePrefix "as-needed" means English has no /en prefix -- the
  // canonical/alternate URLs need to match that exactly, not assume
  // every locale is prefixed.
  const path = locale === routing.defaultLocale ? "" : `/${locale}`;

  return {
    metadataBase: new URL(SITE_URL),
    title,
    description,
    alternates: {
      canonical: `${SITE_URL}${path}`,
      languages: {
        en: SITE_URL,
        es: `${SITE_URL}/es`,
      },
      types: {
        "application/rss+xml": `${SITE_URL}/feed.xml`,
      },
    },
    openGraph: {
      title,
      description,
      url: `${SITE_URL}${path}`,
      siteName: "Futbol Modelo",
      type: "website",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
    },
    manifest: "/manifest.webmanifest",
    appleWebApp: {
      capable: true,
      title: "Futbol Modelo",
      statusBarStyle: "black-translucent",
    },
  };
}

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

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();

  // Static rendering (setRequestLocale) instead of paying the dynamic
  // "reads headers" cost on every request just to know the locale --
  // it's already fixed by the [locale] URL segment.
  setRequestLocale(locale);

  return (
    <html lang={locale} className={`h-full antialiased ${geistSans.variable} ${geistMono.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col font-sans">
        <NextIntlClientProvider>
          <header className="flex items-center justify-between px-4 py-2 border-b border-zinc-100 dark:border-zinc-800">
            <NavLinks />
            <div className="flex items-center gap-3">
              <LocaleSwitcher />
              <ThemeToggle />
            </div>
          </header>
          <AskPeteyDrawer />
          {children}
          <Footer />
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
