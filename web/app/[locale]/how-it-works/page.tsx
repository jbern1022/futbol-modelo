import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";

export default function HowItWorksPage() {
  const t = useTranslations("HowItWorksPage");
  const strong = (chunks: React.ReactNode) => (
    <strong className="text-black dark:text-zinc-50">{chunks}</strong>
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
          {t("notADemo")}
        </p>

        <p className="mt-6 text-zinc-600 dark:text-zinc-400">
          {t("everyMorning")}
        </p>

        <ol className="mt-4 space-y-4 text-zinc-700 dark:text-zinc-300">
          <li className="flex gap-3">
            <span className="font-semibold text-black dark:text-zinc-50">1.</span>
            <span>{t.rich("step1", { strong })}</span>
          </li>
          <li className="flex gap-3">
            <span className="font-semibold text-black dark:text-zinc-50">2.</span>
            <span>{t.rich("step2", { strong })}</span>
          </li>
          <li className="flex gap-3">
            <span className="font-semibold text-black dark:text-zinc-50">3.</span>
            <span>{t.rich("step3", { strong })}</span>
          </li>
          <li className="flex gap-3">
            <span className="font-semibold text-black dark:text-zinc-50">4.</span>
            <span>{t.rich("step4", { strong })}</span>
          </li>
        </ol>

        <p className="mt-8 text-zinc-600 dark:text-zinc-400">
          {t("runsUnattended")}
        </p>

        <p className="mt-6 text-zinc-600 dark:text-zinc-400">
          {t.rich("aboutPetey", { strong })}
        </p>

        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/track-record" className="inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
            {t("seeTrackRecord")} &rarr;
          </Link>
          <Link href="/petey" className="inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
            {t("askPetey")} &rarr;
          </Link>
          <Link href="/data-dictionary" className="inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
            {t("dataDictionary")} &rarr;
          </Link>
          <Link href="/backtest" className="inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
            {t("backtest")} &rarr;
          </Link>
          <Link href="/custom-xg" className="inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
            {t("customXg")} &rarr;
          </Link>
        </div>

        <p className="mt-10 text-sm text-zinc-500 dark:text-zinc-500">
          {t("disclaimer")}
        </p>
      </main>
    </div>
  );
}
