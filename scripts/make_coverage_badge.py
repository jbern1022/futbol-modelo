"""
Writes coverage.svg from the .coverage data file left by
`pytest --cov` (see `make coverage`). Self-contained rather than a
dependency on the coverage-badge package: that package's latest
release imports pkg_resources unconditionally, which recent setuptools
no longer ships -- broken on this Python/setuptools combination with
no fix available from here.

    make coverage   # runs pytest --cov, then this
"""
import sys

import coverage

COLOR_STOPS = [(90, "#4c1"), (75, "#97CA00"), (50, "#dfb317"), (0, "#e05d44")]


def badge_svg(pct: float) -> str:
    color = next(c for threshold, c in COLOR_STOPS if pct >= threshold)
    label, value = "coverage", f"{pct:.0f}%"
    label_w, value_w = 61, 40
    total_w = label_w + value_w
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="20" role="img" aria-label="{label}: {value}">
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="{total_w}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_w}" height="20" fill="#555"/>
    <rect x="{label_w}" width="{value_w}" height="20" fill="{color}"/>
    <rect width="{total_w}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,sans-serif" font-size="11">
    <text x="{label_w / 2:.0f}" y="14">{label}</text>
    <text x="{label_w + value_w / 2:.0f}" y="14">{value}</text>
  </g>
</svg>
'''


def main():
    cov = coverage.Coverage()
    cov.load()
    pct = cov.report(show_missing=False, file=sys.stdout)
    with open("coverage.svg", "w") as f:
        f.write(badge_svg(pct))
    print(f"wrote coverage.svg ({pct:.0f}%)")


if __name__ == "__main__":
    main()
