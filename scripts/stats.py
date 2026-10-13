#!/usr/bin/env python3
"""Generate terminal-style GitHub stats cards (assets/stats.svg, assets/stats-mobile.svg).

Stdlib only. Runs in GitHub Actions (see .github/workflows/stats.yml).
Env: STATS_USER (default ErfanNoch), STATS_TOKEN or GITHUB_TOKEN (optional but recommended).
Flags: --offline  -> render an empty "pending" card without calling the API.
"""
import datetime as dt
import json
import math
import os
import sys
import urllib.request
from xml.sax.saxutils import escape as E

USER = os.environ.get("STATS_USER", "ErfanNoch")
TOKEN = os.environ.get("STATS_TOKEN") or os.environ.get("GITHUB_TOKEN")
OUT = os.environ.get("STATS_OUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")

BG, FG, MU, OR = "#09090b", "#c9c5bd", "#6f6c66", "#D97757"
HEAT = ["#17171a", "#4a2f26", "#7d4b38", "#b5654a", "#D97757"]
FONT = "'JetBrains Mono','Fira Code','SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"


# ---------------------------------------------------------------- data
def api(path, body=None):
    url = "https://api.github.com" + path
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "stats-card"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch():
    d = dict(repos=None, stars=None, commits=None, prs=None, issues=None,
             followers=None, following=None, langs=[], weeks=None, total=None)
    u = api(f"/users/{USER}")
    d.update(repos=u["public_repos"], followers=u["followers"], following=u["following"])

    repos, page = [], 1
    while True:
        chunk = api(f"/users/{USER}/repos?per_page=100&type=owner&page={page}")
        repos += chunk
        if len(chunk) < 100:
            break
        page += 1
    own = [r for r in repos if not r["fork"]]
    d["stars"] = sum(r["stargazers_count"] for r in own)

    langs = {}
    for r in own:
        try:
            for k, v in api(f"/repos/{USER}/{r['name']}/languages").items():
                langs[k] = langs.get(k, 0) + v
        except Exception as e:
            print("lang fetch failed:", r["name"], e, file=sys.stderr)
    d["langs"] = sorted(langs.items(), key=lambda kv: -kv[1])

    for key, q in (("commits", f"/search/commits?q=author:{USER}&per_page=1"),
                   ("prs", f"/search/issues?q=author:{USER}+type:pr&per_page=1"),
                   ("issues", f"/search/issues?q=author:{USER}+type:issue&per_page=1")):
        try:
            d[key] = api(q)["total_count"]
        except Exception as e:
            print(key, "failed:", e, file=sys.stderr)

    try:
        q = ('query($u:String!){user(login:$u){contributionsCollection{contributionCalendar{'
             'totalContributions weeks{contributionDays{contributionCount}}}}}}')
        res = api("/graphql", {"query": q, "variables": {"u": USER}})
        cal = res["data"]["user"]["contributionsCollection"]["contributionCalendar"]
        d["total"] = cal["totalContributions"]
        d["weeks"] = [[day["contributionCount"] for day in w["contributionDays"]] for w in cal["weeks"]]
    except Exception as e:
        print("calendar failed:", e, file=sys.stderr)
    return d


# ---------------------------------------------------------------- render
def fmt(v):
    return "--" if v is None else f"{v:,}"


def level(c, mx):
    if not c:
        return 0
    return max(1, min(4, math.ceil(4 * c / mx)))


def render(d, mobile, pending):
    W = 420 if mobile else 880
    pad = 20 if mobile else 26
    LH = 20
    out = []
    a = out.append

    def prompt(y, tail):
        return (f'<text x="{pad}" y="{y}"><tspan class="o b">erfan@nocha-studio</tspan>'
                f'<tspan class="m">:~$ </tspan>{tail}</text>')

    def header(x, y, title, width):
        a(f'<text x="{x}" y="{y}" class="o b">{E(title)}</text>')
        a(f'<line x1="{x}" y1="{y+7}" x2="{x+width}" y2="{y+7}" stroke="#26262a"/>')

    y = pad + 14
    a(prompt(y, f'gh stats --user {E(USER)}'))

    stats = [("Repos", d["repos"]), ("Stars", d["stars"]), ("Commits", d["commits"]),
             ("Pull Requests", d["prs"]), ("Issues", d["issues"]),
             ("Followers", d["followers"]), ("Following", d["following"])]
    langs = d["langs"][:6]
    total_bytes = sum(v for _, v in d["langs"]) or 1

    # stats column
    x1, y0 = pad, y + 34
    colw1 = (W - 2 * pad) if mobile else 280
    header(x1, y0, "github stats", colw1)
    ry = y0 + 30
    for k, v in stats:
        a(f'<text x="{x1}" y="{ry}" class="o b">{E(k)}</text>')
        a(f'<text x="{x1+124}" y="{ry}" class="m">:</text>')
        a(f'<text x="{x1+138}" y="{ry}">{fmt(v)}</text>')
        ry += LH
    end1 = ry

    # languages column
    if mobile:
        x2, y2 = pad, end1 + 18
    else:
        x2, y2 = 340, y0
    header(x2, y2, "top languages", (W - 2 * pad) if mobile else W - pad - x2)
    ly = y2 + 30
    if langs:
        for name, v in langs:
            pct = 100 * v / total_bytes
            n = round(pct / 100 * 22)
            a(f'<text x="{x2}" y="{ly}">{E(name[:12])}</text>')
            a(f'<text x="{x2+104}" y="{ly}" textLength="173" lengthAdjust="spacingAndGlyphs"><tspan class="o">{"█"*n}</tspan><tspan class="m">{"░"*(22-n)}</tspan></text>')
            a(f'<text x="{x2+104+173+14:.0f}" y="{ly}" class="m">{pct:4.1f}%</text>')
            ly += LH
    else:
        a(f'<text x="{x2}" y="{ly}" class="m">no data yet</text>')
        ly += LH
    end2 = ly
    bottom = end2 if mobile else max(end1, end2)

    # heatmap
    nweeks = 28 if mobile else 53
    step = (W - 2 * pad) / nweeks
    cell = step - 3
    hy = bottom + 22
    header(pad, hy, "contributions", W - 2 * pad)
    a(f'<text x="{W-pad}" y="{hy}" text-anchor="end" class="m">{fmt(d["total"])} in the last year</text>')
    weeks = (d["weeks"] or [])[-nweeks:]
    if not weeks:
        weeks = [[0] * 7 for _ in range(nweeks)]
    mx = max((c for w in weeks for c in w), default=0) or 1
    gx = pad if not mobile else pad
    for i, w in enumerate(weeks):
        for j, c in enumerate(w):
            a(f'<rect x="{gx+i*step:.1f}" y="{hy+20+j*step:.1f}" width="{cell:.1f}" height="{cell:.1f}" rx="1.5" fill="{HEAT[level(c, mx)]}"/>')
    fy = round(hy + 20 + 7 * step + 18)
    a(f'<text x="{pad}" y="{fy}" class="m"># {"pending first workflow run" if pending else "auto-updated by github actions"}</text>')
    H = fy + pad - 4

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
           f'aria-label="GitHub stats for {E(USER)}: repositories, stars, commits, pull requests, issues, followers, top languages and contribution heatmap.">',
           f'<style>text{{font-family:{FONT};font-size:13px;fill:{FG};white-space:pre}}'
           f'.o{{fill:{OR}}}.b{{font-weight:700}}.m{{fill:{MU}}}</style>',
           f'<rect width="{W}" height="{H}" rx="10" fill="{BG}"/>',
           f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="10" fill="none" stroke="#26262a"/>']
    return "\n".join(svg + out + ["</svg>"])


def main():
    pending = "--offline" in sys.argv
    if pending:
        d = dict(repos=None, stars=None, commits=None, prs=None, issues=None,
                 followers=None, following=None, langs=[], weeks=None, total=None)
    else:
        d = fetch()
    os.makedirs(OUT, exist_ok=True)
    for name, m in (("stats.svg", False), ("stats-mobile.svg", True)):
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            f.write(render(d, m, pending))
        print("wrote", name)


if __name__ == "__main__":
    main()
