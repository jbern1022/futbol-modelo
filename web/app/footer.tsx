export default function Footer() {
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
      </p>
    </footer>
  );
}
