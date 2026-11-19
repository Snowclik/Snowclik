#!/usr/bin/env python3
"""Genera assets/radar.svg: panel Cyber-Ártico con radar de lenguajes y métricas reales.

Usa únicamente la biblioteca estándar de Python 3.
- Con GITHUB_TOKEN (en GitHub Actions o local): consulta la API GraphQL de GitHub.
- Sin GITHUB_TOKEN (local): consulta la API REST pública de GitHub.
"""

from __future__ import annotations

import html
import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USER = os.environ.get("GH_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "Snowclik"
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
ROOT_DIR = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("RADAR_OUT", str(ROOT_DIR / "assets" / "radar.svg")))

TOP_N = 6
IGNORE_REPOS = {"Artalk", "Snowclik", "is-a-software"}
IGNORE_LANGS: set[str] = set()

FONT_SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
FONT_MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"

LANG_COLORS: dict[str, str] = {
    "TypeScript": "#38BDF8",
    "Python": "#A78BFA",
    "Rust": "#FB923C",
    "Kotlin": "#C084FC",
    "JavaScript": "#FACC15",
    "HTML": "#F87171",
    "CSS": "#F472B6",
    "Astro": "#FF5D01",
    "C#": "#34D399",
    "Go": "#22D3EE",
    "Shell": "#4ADE80",
    "SCSS": "#EC4899",
    "Vue": "#34D399",
    "PowerShell": "#60A5FA",
}
FALLBACK_COLORS = ["#38BDF8", "#A78BFA", "#34D399", "#F472B6", "#FACC15", "#FB923C"]

GRAPHQL_QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    createdAt
    pullRequests { totalCount }
    contributionsCollection { totalCommitContributions }
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        stargazerCount
        languages(first: 15, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""


def _http_json(url: str, *, method: str = "GET", body: dict | None = None, token: str | None = None) -> dict | list:
    headers = {
        "User-Agent": "Snowclik-Radar-Generator",
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_via_graphql(user: str, token: str) -> dict[str, object]:
    langs: dict[str, int] = {}
    repos_count = 0
    stars = 0
    commits = 0
    prs = 0
    since_year = "2020"
    after: str | None = None

    while True:
        payload = _http_json(
            "https://api.github.com/graphql",
            method="POST",
            body={"query": GRAPHQL_QUERY, "variables": {"login": user, "after": after}},
            token=token,
        )
        if not isinstance(payload, dict) or "errors" in payload:
            raise RuntimeError(f"GraphQL error: {payload}")

        u = payload["data"]["user"]
        created_at = u.get("createdAt") or "2020-01-01T00:00:00Z"
        since_year = created_at[:4]
        prs = int(u["pullRequests"]["totalCount"])
        commits = int(u["contributionsCollection"]["totalCommitContributions"])

        repo_conn = u["repositories"]
        for node in repo_conn["nodes"]:
            if node["name"] in IGNORE_REPOS:
                continue
            repos_count += 1
            stars += int(node.get("stargazerCount", 0))
            for edge in node["languages"]["edges"]:
                lname = edge["node"]["name"]
                if lname in IGNORE_LANGS:
                    continue
                langs[lname] = langs.get(lname, 0) + int(edge["size"])

        page_info = repo_conn["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        after = page_info["endCursor"]

    return {
        "langs": langs,
        "repos": repos_count,
        "stars": stars,
        "metric_3_label": "COMMITS",
        "metric_3_val": str(commits),
        "metric_4_label": "PULL REQUESTS" if prs > 0 else "DESDE",
        "metric_4_val": str(prs) if prs > 0 else since_year,
    }


def fetch_via_rest(user: str) -> dict[str, object]:
    user_info = _http_json(f"https://api.github.com/users/{user}")
    assert isinstance(user_info, dict)
    created_at = str(user_info.get("created_at", "2020-01-01T00:00:00Z"))
    since_year = created_at[:4]
    years_active = max(1, datetime.now(timezone.utc).year - int(since_year) + 1)

    repos = _http_json(f"https://api.github.com/users/{user}/repos?per_page=100&type=owner")
    assert isinstance(repos, list)

    langs: dict[str, int] = {}
    repos_count = 0
    stars = 0

    for repo in repos:
        if repo.get("fork") or repo.get("name") in IGNORE_REPOS:
            continue
        repos_count += 1
        stars += int(repo.get("stargazers_count", 0))
        lang_url = repo.get("languages_url")
        if lang_url:
            repo_langs = _http_json(str(lang_url))
            if isinstance(repo_langs, dict):
                for lname, bcount in repo_langs.items():
                    if lname in IGNORE_LANGS:
                        continue
                    langs[lname] = langs.get(lname, 0) + int(bcount)

    return {
        "langs": langs,
        "repos": repos_count,
        "stars": stars,
        "metric_3_label": "LENGUAJES",
        "metric_3_val": str(len(langs)),
        "metric_4_label": "DESDE",
        "metric_4_val": f"{since_year} ({years_active}a)",
    }


def format_bytes(num_bytes: int) -> str:
    if num_bytes >= 1_000_000:
        return f"{num_bytes / 1_000_000:.1f} MB"
    if num_bytes >= 1_000:
        return f"{num_bytes / 1_000:.1f} KB"
    return f"{num_bytes} B"


def build_radar_svg(data: dict[str, object]) -> str:
    langs_raw: dict[str, int] = dict(data["langs"])  # type: ignore[arg-type]
    if not langs_raw:
        raise RuntimeError("No se encontraron lenguajes para generar el radar.")

    total_bytes = sum(langs_raw.values())
    sorted_langs = sorted(langs_raw.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]
    # Para formar un polígono válido se requieren al menos 3 ejes
    while len(sorted_langs) < 3:
        sorted_langs.append(("Otro", 0))

    max_bytes = max(val for _, val in sorted_langs) or 1
    n_axes = len(sorted_langs)

    cx, cy, max_r = 205.0, 222.0, 108.0

    # Anillos concéntricos y ejes radiales
    rings_svg: list[str] = []
    for level in (0.25, 0.50, 0.75, 1.0):
        r = max_r * level
        pts = []
        for i in range(n_axes):
            ang = -math.pi / 2 + (2 * math.pi * i / n_axes)
            pts.append(f"{cx + r * math.cos(ang):.1f},{cy + r * math.sin(ang):.1f}")
        dash = ' stroke-dasharray="3 3"' if level < 1.0 else ""
        rings_svg.append(
            f'<polygon points="{" ".join(pts)}" fill="none" stroke="#1E293B" stroke-width="1"{dash}/>'
        )

    axes_svg: list[str] = []
    labels_svg: list[str] = []
    poly_pts: list[str] = []
    vertices_svg: list[str] = []

    for i, (lname, bcount) in enumerate(sorted_langs):
        ang = -math.pi / 2 + (2 * math.pi * i / n_axes)
        cos_a = math.cos(ang)
        sin_a = math.sin(ang)

        ex = cx + max_r * cos_a
        ey = cy + max_r * sin_a
        axes_svg.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="#1E293B" stroke-width="1"/>')

        ratio = (bcount / max_bytes) if max_bytes > 0 else 0.0
        scaled_r = max_r * (0.18 + 0.82 * math.sqrt(ratio)) if bcount > 0 else max_r * 0.14
        vx = cx + scaled_r * cos_a
        vy = cy + scaled_r * sin_a
        poly_pts.append(f"{vx:.1f},{vy:.1f}")

        color = LANG_COLORS.get(lname, FALLBACK_COLORS[i % len(FALLBACK_COLORS)])
        pct = (bcount / total_bytes * 100.0) if total_bytes > 0 else 0.0

        # Etiqueta del eje
        lx = cx + (max_r + 18.0) * cos_a
        ly = cy + (max_r + 18.0) * sin_a + 3.5
        if abs(cos_a) < 0.2:
            anchor = "middle"
        elif cos_a > 0:
            anchor = "start"
        else:
            anchor = "end"

        labels_svg.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
            f'font-family="{FONT_SANS}" font-size="11" font-weight="600" fill="#CBD5E1">{html.escape(lname)}</text>'
        )

        # Vértice interactivo con tooltip
        tip_w = max(84, len(lname) * 6.8 + 44)
        tip_x = max(14.0, min(390.0 - tip_w, vx - tip_w / 2.0))
        tip_y = vy - 30.0 if vy > 86 else vy + 12.0
        vertices_svg.append(
            f"""<g class="pt">
        <circle cx="{vx:.1f}" cy="{vy:.1f}" r="11" fill="transparent"/>
        <circle class="dot" cx="{vx:.1f}" cy="{vy:.1f}" r="4.2" fill="{color}" stroke="#070B14" stroke-width="1.5"/>
        <g class="tip">
          <rect x="{tip_x:.1f}" y="{tip_y:.1f}" width="{tip_w:.1f}" height="22" rx="6" fill="#0F172A" stroke="{color}" stroke-width="1"/>
          <text x="{tip_x + tip_w / 2.0:.1f}" y="{tip_y + 14.5:.1f}" text-anchor="middle" font-family="{FONT_MONO}" font-size="10" font-weight="600" fill="#F8FAFC">{html.escape(lname)} · {pct:.1f}%</text>
        </g>
      </g>"""
        )

    # Ranking derecho
    rows_svg: list[str] = []
    bar_x = 434.0
    bar_w = 376.0
    y0 = 76.0
    step_y = 33.0
    for i, (lname, bcount) in enumerate(sorted_langs):
        color = LANG_COLORS.get(lname, FALLBACK_COLORS[i % len(FALLBACK_COLORS)])
        pct = (bcount / total_bytes * 100.0) if total_bytes > 0 else 0.0
        fill_w = max(6.0, bar_w * (pct / 100.0))
        ry = y0 + i * step_y
        delay = f"{i * 0.08:.2f}s"
        rows_svg.append(
            f"""<g class="row">
        <rect class="hit" x="422" y="{ry - 14:.1f}" width="402" height="28" rx="6" fill="#38BDF8"/>
        <circle cx="439" cy="{ry - 3:.1f}" r="3.8" fill="{color}"/>
        <text x="450" y="{ry + 0.5:.1f}" font-family="{FONT_SANS}" font-size="12" font-weight="600" fill="#E2E8F0">{html.escape(lname)}</text>
        <text x="810" y="{ry + 0.5:.1f}" text-anchor="end" font-family="{FONT_MONO}" font-size="11" fill="#94A3B8">{pct:.1f}%  ·  {format_bytes(bcount)}</text>
        <rect x="{bar_x:.1f}" y="{ry + 7:.1f}" width="{bar_w:.1f}" height="5" rx="2.5" fill="#151E2E"/>
        <rect class="bf" style="animation-delay:{delay}" x="{bar_x:.1f}" y="{ry + 7:.1f}" width="{fill_w:.1f}" height="5" rx="2.5" fill="{color}"/>
      </g>"""
        )

    # 4 tarjetas de métricas inferiores
    cards = [
        ("REPOS PROPIOS", str(data["repos"]), "#38BDF8"),
        ("ESTRELLAS", str(data["stars"]), "#A78BFA"),
        (str(data["metric_3_label"]), str(data["metric_3_val"]), "#34D399"),
        (str(data["metric_4_label"]), str(data["metric_4_val"]), "#F472B6"),
    ]
    cards_svg: list[str] = []
    card_w = 96.0
    card_gap = 8.0
    for idx, (lbl, val, col) in enumerate(cards):
        kx = 422.0 + idx * (card_w + card_gap)
        cards_svg.append(
            f"""<rect x="{kx:.1f}" y="294" width="{card_w:.1f}" height="74" rx="10" fill="#0B1220" stroke="#1E293B" stroke-width="1"/>
      <text x="{kx + 12:.1f}" y="317" font-family="{FONT_MONO}" font-size="8.8" font-weight="600" letter-spacing="0.5" fill="#64748B">{html.escape(lbl)}</text>
      <text x="{kx + 12:.1f}" y="349" font-family="{FONT_SANS}" font-size="18" font-weight="700" fill="{col}">{html.escape(val)}</text>"""
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 392" width="860" height="392" role="img" aria-label="Radar de lenguajes y estadísticas de {html.escape(USER)}">
  <defs>
    <linearGradient id="radar-bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#070B14"/>
      <stop offset="100%" stop-color="#0D1117"/>
    </linearGradient>
    <radialGradient id="aurora-l" cx="24%" cy="54%" r="42%">
      <stop offset="0%" stop-color="#38BDF8" stop-opacity="0.12"/>
      <stop offset="100%" stop-color="#38BDF8" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="aurora-r" cx="85%" cy="18%" r="40%">
      <stop offset="0%" stop-color="#A78BFA" stop-opacity="0.10"/>
      <stop offset="100%" stop-color="#A78BFA" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="poly-fill" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#38BDF8"/>
      <stop offset="100%" stop-color="#A78BFA"/>
    </linearGradient>
    <linearGradient id="top-shine" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#38BDF8" stop-opacity="0"/>
      <stop offset="50%" stop-color="#A78BFA" stop-opacity="0.5"/>
      <stop offset="100%" stop-color="#38BDF8" stop-opacity="0"/>
    </linearGradient>
    <style>
      .rp {{
        transform-origin: {cx:.1f}px {cy:.1f}px;
        animation: gp 0.9s cubic-bezier(0.22, 1, 0.36, 1) backwards;
        transition: fill-opacity 0.2s;
      }}
      .rp:hover {{ fill-opacity: 0.42; }}
      .bf {{
        transform-box: fill-box;
        transform-origin: left center;
        animation: gb 0.85s cubic-bezier(0.22, 1, 0.36, 1) backwards;
        transition: transform 0.2s;
      }}
      .row {{ transition: opacity 0.2s; }}
      .row .hit {{ fill-opacity: 0; transition: fill-opacity 0.2s; }}
      .row:hover .hit {{ fill-opacity: 0.08; }}
      .row:hover .bf {{ transform: scaleY(1.7); }}
      .rows:hover .row {{ opacity: 0.45; }}
      .rows .row:hover {{ opacity: 1; }}
      .tip {{ opacity: 0; pointer-events: none; transition: opacity 0.15s; }}
      .pt:hover .tip {{ opacity: 1; }}
      .dot {{ transition: r 0.15s; }}
      .pt:hover .dot {{ r: 6; }}
      @keyframes gp {{ from {{ transform: scale(0.1); opacity: 0; }} }}
      @keyframes gb {{ from {{ transform: scaleX(0); }} }}
      @media (prefers-reduced-motion: reduce) {{
        * {{ animation: none !important; transition: none !important; }}
      }}
    </style>
  </defs>

  <rect x="0.5" y="0.5" width="859" height="391" rx="16" fill="url(#radar-bg)" stroke="#1E293B" stroke-width="1"/>
  <rect x="1" y="1" width="858" height="390" rx="15" fill="url(#aurora-l)"/>
  <rect x="1" y="1" width="858" height="390" rx="15" fill="url(#aurora-r)"/>
  <line x1="120" y1="1" x2="740" y2="1" stroke="url(#top-shine)" stroke-width="1"/>

  <!-- Panel izquierdo: Radar -->
  <rect x="18" y="18" width="382" height="356" rx="12" fill="#0B1220" fill-opacity="0.72" stroke="#1E293B" stroke-width="1"/>
  <text x="36" y="44" font-family="{FONT_MONO}" font-size="10.5" font-weight="700" letter-spacing="1.2" fill="#38BDF8">✦ RADAR DE LENGUAJES</text>
  <text x="36" y="61" font-family="{FONT_SANS}" font-size="11.5" fill="#64748B">Proporción real en repositorios propios</text>

  {"".join(rings_svg)}
  {"".join(axes_svg)}
  <polygon class="rp" points="{" ".join(poly_pts)}" fill="url(#poly-fill)" fill-opacity="0.26" stroke="#38BDF8" stroke-width="2" stroke-linejoin="round"/>
  {"".join(labels_svg)}
  {"".join(vertices_svg)}

  <!-- Panel derecho: Ranking y métricas -->
  <text x="424" y="44" font-family="{FONT_MONO}" font-size="10.5" font-weight="700" letter-spacing="1.2" fill="#A78BFA">TOP LENGUAJES</text>
  <rect x="752" y="29" width="78" height="20" rx="6" fill="#0C2336" stroke="#164E63" stroke-width="1"/>
  <text x="791" y="42.5" text-anchor="middle" font-family="{FONT_MONO}" font-size="9.5" font-weight="700" letter-spacing="0.8" fill="#38BDF8">{html.escape(USER.upper())}</text>

  <g class="rows">
    {"".join(rows_svg)}
  </g>

  {"".join(cards_svg)}
</svg>
"""


def main() -> None:
    try:
        if TOKEN:
            data = fetch_via_graphql(USER, TOKEN)
        else:
            data = fetch_via_rest(USER)
    except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as exc:
        print(f"ERROR obteniendo datos de GitHub para {USER}: {exc}", file=sys.stderr)
        sys.exit(1)

    svg = build_radar_svg(data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(svg, encoding="utf-8")
    print(f"Radar generado en {OUT} ({len(svg)} bytes)")


if __name__ == "__main__":
    main()
