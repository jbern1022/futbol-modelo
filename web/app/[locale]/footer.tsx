"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

interface PipelineJob {
  job_name: string;
  status: "running" | "success" | "failed";
  started_at: string;
  finished_at: string | null;
  rows_written: number | null;
}

type TranslateFn = (key: string, values?: Record<string, string | number>) => string;

function timeAgo(iso: string, t: TranslateFn): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return t("justNow");
  if (mins < 60) return t("minutesAgo", { mins });
  const hours = Math.floor(mins / 60);
  if (hours < 24) return t("hoursAgo", { hours });
  const days = Math.floor(hours / 24);
  return t("daysAgo", { days });
}

// Client-side fetch, not a server-rendered one -- Footer renders on
// every page including ones Next.js statically prerenders at
// docker-host build time, which has no network route to the
// cluster-internal API. A server-side fetch here would bake a
// permanent "no freshness data" state into those pages' static HTML
// (real incident, 2026-08-29: this exact thing silently dropped the
// "Predictions last generated Xh ago" text from every static page).
// The visitor's own browser always has real internet access to the
// public /api/pipeline-status proxy, so this sidesteps the problem
// entirely instead of forcing every page in the app to render
// dynamically just for one line of footer text.
function useFreshness(t: TranslateFn): string | null {
  const [freshness, setFreshness] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/pipeline-status")
      .then((res) => (res.ok ? res.json() : null))
      .then((data: { jobs: PipelineJob[] } | null) => {
        if (cancelled || !data) return;
        const successTimes = data.jobs
          .filter((j) => j.job_name.startsWith("auto_slate:") && j.status === "success" && j.finished_at)
          .map((j) => j.finished_at as string);
        if (successTimes.length === 0) return;
        const latest = successTimes.reduce((a, b) => (a > b ? a : b));
        setFreshness(timeAgo(latest, t));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [t]);

  return freshness;
}

export default function Footer() {
  const t = useTranslations("Footer");
  const freshness = useFreshness(t);

  return (
    <footer className="mt-auto border-t border-zinc-200 py-6 text-center text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-500">
      <p>
        {t("dataFrom")}{" "}
        <a href="https://fbref.com" className="hover:underline" target="_blank" rel="noopener noreferrer">
          FBref
        </a>
        ,{" "}
        <a href="https://understat.com" className="hover:underline" target="_blank" rel="noopener noreferrer">
          Understat
        </a>
        , {t("and")}{" "}
        <a href="https://www.api-football.com" className="hover:underline" target="_blank" rel="noopener noreferrer">
          API-Football
        </a>
        .{" "}
        <a
          href="https://github.com/jbern1022/futbol-modelo"
          className="hover:underline"
          target="_blank"
          rel="noopener noreferrer"
        >
          {t("sourceOnGitHub")}
        </a>
        {" "}&middot;{" "}
        <a href="/api/docs" className="hover:underline">
          {t("apiDocs")}
        </a>
        {" "}&middot;{" "}
        <a href="/feed.xml" className="hover:underline">
          RSS
        </a>
        {freshness && <> &middot; {t("predictionsLastGenerated", { time: freshness })}</>}
      </p>
    </footer>
  );
}
