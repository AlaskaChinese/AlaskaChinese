#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

API = "https://api.github.com"
USERNAME = os.environ.get("PROFILE_USERNAME", "AlaskaChinese")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT_DIR = Path("assets/profile")

HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "profile-stats-generator",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

LANG_COLORS = {
    "C": "#555555",
    "C++": "#f34b7d",
    "Python": "#3572A5",
    "Verilog": "#b2b7f8",
    "SystemVerilog": "#DAE1C2",
    "MATLAB": "#e16737",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "Shell": "#89e051",
    "CMake": "#DA3434",
    "Makefile": "#427819",
    "Java": "#b07219",
    "Go": "#00ADD8",
    "Rust": "#dea584",
    "Scala": "#c22d40",
    "Jupyter Notebook": "#DA5B0B",
    "Lua": "#000080",
}


def api_json(path: str, params: dict | None = None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def graphql(query: str, variables: dict):
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN is required for GraphQL stats")
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    headers = dict(HEADERS)
    headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        API + "/graphql", data=payload, headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


def list_repositories():
    repos = []
    page = 1
    while True:
        batch = api_json(
            f"/users/{USERNAME}/repos",
            {"type": "owner", "sort": "updated", "per_page": 100, "page": page},
        )
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def get_core_stats():
    query = """
    query($login: String!) {
      user(login: $login) {
        commits: contributionsCollection {
          totalCommitContributions
        }
        reviews: contributionsCollection {
          totalPullRequestReviewContributions
        }
        pullRequests(first: 1) {
          totalCount
        }
        issues(first: 1) {
          totalCount
        }
        followers {
          totalCount
        }
      }
    }
    """
    user = graphql(query, {"login": USERNAME})["user"]
    return {
        "commits_last_year": int(user["commits"]["totalCommitContributions"]),
        "reviews": int(user["reviews"]["totalPullRequestReviewContributions"]),
        "prs": int(user["pullRequests"]["totalCount"]),
        "issues": int(user["issues"]["totalCount"]),
        "followers": int(user["followers"]["totalCount"]),
    }


def get_languages(repos):
    totals = Counter()
    for repo in repos:
        if repo.get("fork") or repo.get("archived") or repo.get("size", 0) == 0:
            continue
        try:
            langs = api_json(f"/repos/{repo['full_name']}/languages")
        except Exception as exc:
            print(f"warning: languages failed for {repo['full_name']}: {exc}")
            continue
        totals.update({name: int(size) for name, size in langs.items()})
    return totals


def calculate_rank(stats: dict):
    # Mirrors github-readme-stats/src/calculateRank.js with include_all_commits=false.
    def exponential_cdf(x: float) -> float:
        return 1 - 2 ** (-x)

    def log_normal_cdf(x: float) -> float:
        return x / (1 + x)

    weighted = (
        2 * exponential_cdf(stats["commits_last_year"] / 250)
        + 3 * exponential_cdf(stats["prs"] / 50)
        + 1 * exponential_cdf(stats["issues"] / 25)
        + 1 * exponential_cdf(stats["reviews"] / 2)
        + 4 * log_normal_cdf(stats["stars"] / 50)
        + 1 * log_normal_cdf(stats["followers"] / 10)
    )
    percentile = (1 - weighted / 12) * 100
    thresholds = [1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100]
    levels = ["S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]
    level = levels[-1]
    for threshold, candidate in zip(thresholds, levels):
        if percentile <= threshold:
            level = candidate
            break
    return {"level": level, "percentile": percentile}


def fmt(value):
    value = int(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m"
    if value >= 100_000:
        return f"{value / 1000:.0f}k"
    if value >= 10_000:
        return f"{value / 1000:.1f}k"
    return f"{value:,}"


def theme(name: str):
    if name == "dark":
        return {
            "bg": "#0d1117",
            "border": "#30363d",
            "title": "#58a6ff",
            "text": "#c9d1d9",
            "muted": "#8b949e",
            "track": "#21262d",
            "rank": "#58a6ff",
        }
    return {
        "bg": "#ffffff",
        "border": "#d0d7de",
        "title": "#0969da",
        "text": "#24292f",
        "muted": "#57606a",
        "track": "#eaeef2",
        "rank": "#0969da",
    }


def svg_open(width, height, palette):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">
<style>
  text {{ font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }}
</style>
<rect x="0.5" y="0.5" width="{width-1}" height="{height-1}" rx="10" fill="{palette['bg']}" stroke="{palette['border']}"/>
'''


def stats_svg(stats: dict, theme_name: str):
    p = theme(theme_name)
    width, height = 520, 218
    rows = [
        ("Total Stars Earned", stats["stars"]),
        ("Total Commits (last year)", stats["commits_last_year"]),
        ("Total PRs", stats["prs"]),
        ("Total Issues", stats["issues"]),
        ("Public Repositories", stats["repos"]),
    ]
    rank = stats["rank"]
    out = [svg_open(width, height, p)]
    out.append(f'<text x="24" y="36" font-size="20" font-weight="700" fill="{p["title"]}">{html.escape(USERNAME)}\'s GitHub Stats</text>')
    for i, (label, value) in enumerate(rows):
        y = 72 + i * 28
        out.append(f'<text x="28" y="{y}" font-size="13" font-weight="600" fill="{p["text"]}">{html.escape(label)}:</text>')
        out.append(f'<text x="330" y="{y}" text-anchor="end" font-size="13" font-weight="700" fill="{p["text"]}">{fmt(value)}</text>')

    cx, cy, r = 430, 124, 44
    circumference = 2 * math.pi * r
    completion = max(0.0, min(100.0, 100.0 - rank["percentile"]))
    dash = circumference * completion / 100
    gap = circumference - dash
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{p["track"]}" stroke-width="8"/>')
    out.append(
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{p["rank"]}" stroke-width="8" '
        f'stroke-linecap="round" stroke-dasharray="{dash:.2f} {gap:.2f}" transform="rotate(-90 {cx} {cy})"/>'
    )
    out.append(f'<text x="{cx}" y="{cy+8}" text-anchor="middle" font-size="28" font-weight="800" fill="{p["text"]}">{html.escape(rank["level"])}</text>')
    out.append(f'<text x="{cx}" y="{cy+70}" text-anchor="middle" font-size="11" fill="{p["muted"]}">Rank · top {rank["percentile"]:.1f}%</text>')
    out.append("</svg>")
    return "\n".join(out)


def fallback_color(name: str):
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()
    return "#" + digest[:6]


def languages_svg(languages: Counter, theme_name: str):
    p = theme(theme_name)
    width, height = 520, 246
    total = sum(languages.values())
    top = languages.most_common(6)
    out = [svg_open(width, height, p)]
    out.append(f'<text x="24" y="36" font-size="20" font-weight="700" fill="{p["title"]}">Most Used Languages</text>')
    x, y, bar_w, bar_h = 24.0, 58, 472.0, 12
    out.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" rx="6" fill="{p["track"]}"/>')
    cursor = x
    if total:
        for name, amount in top:
            frac = amount / total
            seg_w = bar_w * frac
            color = LANG_COLORS.get(name, fallback_color(name))
            out.append(f'<rect x="{cursor:.2f}" y="{y}" width="{seg_w:.2f}" height="{bar_h}" fill="{color}"/>')
            cursor += seg_w
    else:
        out.append(f'<text x="24" y="108" font-size="14" fill="{p["muted"]}">Language data will appear after the next update.</text>')

    positions = [(24, 108), (282, 108), (24, 150), (282, 150), (24, 192), (282, 192)]
    for (name, amount), (lx, ly) in zip(top, positions):
        pct = (amount / total * 100) if total else 0
        color = LANG_COLORS.get(name, fallback_color(name))
        label = html.escape(name)
        out.append(f'<circle cx="{lx+6}" cy="{ly-5}" r="6" fill="{color}"/>')
        out.append(f'<text x="{lx+20}" y="{ly}" font-size="14" fill="{p["text"]}">{label} {pct:.1f}%</text>')
    out.append(f'<text x="24" y="228" font-size="11" fill="{p["muted"]}">Calculated from public, non-fork repositories using GitHub Linguist data.</text>')
    out.append("</svg>")
    return "\n".join(out)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    repos = list_repositories()
    core = get_core_stats()
    stats = {
        **core,
        "stars": sum(int(repo.get("stargazers_count", 0)) for repo in repos if not repo.get("fork")),
        "repos": sum(1 for repo in repos if not repo.get("fork")),
    }
    stats["rank"] = calculate_rank(stats)
    languages = get_languages(repos)

    for mode in ("light", "dark"):
        (OUT_DIR / f"stats-{mode}.svg").write_text(stats_svg(stats, mode), encoding="utf-8")
        (OUT_DIR / f"languages-{mode}.svg").write_text(languages_svg(languages, mode), encoding="utf-8")

    print("generated profile cards")
    print(stats)
    print(languages.most_common(10))


if __name__ == "__main__":
    main()
