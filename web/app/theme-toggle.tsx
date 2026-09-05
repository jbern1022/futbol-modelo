"use client";

import { useEffect, useState } from "react";

export default function ThemeToggle() {
  const [isDark, setIsDark] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setIsDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !isDark;
    setIsDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
  }

  if (!mounted) {
    return <div className="h-8 w-8" />;
  }

  return (
    <button onClick={toggle} aria-label="Toggle dark mode" className="flex h-9 w-9 items-center justify-center rounded-full border border-zinc-300 bg-white text-zinc-700 shadow-md hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700">
      {isDark ? "\u2600" : "\u263D"}
    </button>
  );
}
