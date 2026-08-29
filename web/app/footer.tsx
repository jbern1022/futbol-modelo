"use client";

import { useEffect, useState } from "react";

interface PipelineJob {
  job_name: string;
  status: "running" | "success" | "failed";
  started_at: string;
  finished_at: string | null;
  rows_written: number | null;
}

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
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
function useFreshness(): string | null {
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
        setFreshness(timeAgo(latest));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return freshness;
}

export default function Footer() {
  const freshness = useFreshness();

  return (
    <footer className="mt-auto border-t border-zinc-200 py-6 text-center text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-500">
      <p>
        Data from{" "}
        <a href="https://fbref.com" className="hover:underline" target="_blank" rel="noopener noreferrer">
          FBref
        </a>
        ,{" "}
        <a href="https://understat.com" className="hover:underline" target="_blank" rel="noopener noreferrer">
          Understat
        </a>
        , and{" "}
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
          Source on GitHub
        </a>
        {" "}&middot;{" "}
        <a href="/api/docs" className="hover:underline">
          API docs
        </a>
        {" "}&middot;{" "}
        <a href="/feed.xml" className="hover:underline">
          RSS
        </a>
        {freshness && <> &middot; Predictions last generated {freshness}</>}
      </p>
    </footer>
  );
}
