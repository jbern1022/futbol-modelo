import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";

export default function LessonsLearnedPage() {
  const t = useTranslations("LessonsLearnedPage");
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>;
  const code = (chunks: React.ReactNode) => (
    <code className="rounded bg-zinc-100 px-1 py-0.5 text-sm dark:bg-zinc-900">{chunks}</code>
  );
  const customXgLink = (chunks: React.ReactNode) => (
    <Link href="/custom-xg" className="underline hover:no-underline">{chunks}</Link>
  );
  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; {t("backToFixtures")}
        </Link>

        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          {t("heading")}
        </h1>
        <p className="mt-4 text-zinc-600 dark:text-zinc-400">
          {t.rich("intro", { em })}
        </p>

        <div className="mt-10 space-y-10">
          <section>
            <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
              {t("uniquenessHeading")}
            </h2>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              {t.rich("uniquenessBody", { code })}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
              {t("peteyBodyCountHeading")}
            </h2>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              {t("peteyBodyCountBody")}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
              {t("hostnameHeading")}
            </h2>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              {t.rich("hostnameBody", { em })}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
              {t("secretHeading")}
            </h2>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              {t.rich("secretBody", { code })}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
              {t("fixedTestedShippedHeading")}
            </h2>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              {t.rich("fixedTestedShippedBody", { em })}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
              {t("stepAssumedHeading")}
            </h2>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              {t("stepAssumedBody")}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
              {t("substringHeading")}
            </h2>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              {t("substringBody")}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
              {t("renameHeading")}
            </h2>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              {t("renameBody")}
            </p>
          </section>

          <section id="mls-xg-data-gap">
            <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
              {t("mlsXgHeading")}
            </h2>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              {t.rich("mlsXgBody1", { customXgLink })}
            </p>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              {t("mlsXgBody2")}
            </p>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              {t("mlsXgBody3")}
            </p>
          </section>
        </div>

        <p className="mt-10 text-zinc-600 dark:text-zinc-400">
          {t("closing")}
        </p>

        <Link href="/how-it-works" className="mt-8 inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
          {t("howItWorks")} &rarr;
        </Link>
      </main>
    </div>
  );
}
