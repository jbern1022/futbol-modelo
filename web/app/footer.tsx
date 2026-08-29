const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

async function getFreshness(): Promise<string | null> {
  try {
    const res = await fetch(`${API_URL}/pipeline-status`, { cache: "no-store" });
    if (!res.ok) return null;
    const data: { jobs: PipelineJob[] } = await res.json();
    const successTimes = data.jobs
      .filter((j) => j.job_name.startsWith("auto_slate:") && j.status === "success" && j.finished_at)
      .map((j) => j.finished_at as string);
    if (successTimes.length === 0) return null;
    const latest = successTimes.reduce((a, b) => (a > b ? a : b));
    return timeAgo(latest);
  } catch {
    return null;
  }
}

export default async function Footer() {
  const freshness = await getFreshness();

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
