import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";

export default function NotFound() {
  const t = useTranslations("NotFoundPage");
  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <h1 className="text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          {t("heading")}
        </h1>
        <p className="mt-4 text-zinc-600 dark:text-zinc-400">
          {t("explainer")}
        </p>
        <Link
          href="/"
          className="mt-8 inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
        >
          &larr; {t("backToFixtures")}
        </Link>
      </main>
    </div>
  );
}
