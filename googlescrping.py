
import requests
from bs4 import BeautifulSoup
import sqlite3
import csv
import time
import re

url = "https://github.com/orgs/google/repositories"
headers = {"User-Agent": "Mozilla/5.0"}

languages = {
    "Python", "Java", "JavaScript", "TypeScript",
    "Go", "C++", "C", "C#", "Rust", "Kotlin",
    "Dart", "Swift", "Objective-C", "Objective-C++",
    "Ruby", "PHP", "HTML", "CSS", "Shell",
    "Jupyter Notebook", "R", "Scala", "Lua",
    "Perl", "Haskell", "Clojure", "Elixir",
    "Erlang", "Assembly", "PowerShell",
    "Vim Script", "Makefile", "CMake",
    "Dockerfile", "SCSS", "Sass", "Less",
    "Nix", "Starlark", "Groovy", "MATLAB",
    "Julia", "D", "F#", "OCaml", "Fortran",
    "CoffeeScript", "Batchfile", "TeX",
    "Vue", "Svelte", "Solidity", "Zig",
    "Prolog", "SQL", "PLpgSQL", "WebAssembly",
    "GDScript", "Common Lisp", "Emacs Lisp",
    "VHDL", "Verilog", "SystemVerilog",
    "Protocol Buffer", "Jsonnet", "Tcl",
    "Awk", "Puppet", "HCL"
}


def get_language(card):
    tag = card.select_one(
        '[itemprop="programmingLanguage"], '
        '[data-testid="repository-language"], '
        '[data-testid="repository-primary-language"]'
    )

    if tag and tag.get_text(" ", strip=True):
        return tag.get_text(" ", strip=True)

    for dot in card.select(
        '.repo-language-color, [style*="background-color"]'
    ):
        value = dot.parent.get_text(" ", strip=True)

        if value in languages:
            return value

        next_tag = dot.find_next_sibling("span")

        if next_tag:
            value = next_tag.get_text(" ", strip=True)

            if value in languages:
                return value

    for value in reversed(list(card.stripped_strings)):
        if value in languages:
            return value

    return "不明"


def get_card(h3):
    card = h3.find_parent("li")

    if card is None:
        card = h3.find_parent("article")

    if card is not None:
        return card

    candidate = None

    for parent in h3.parents:
        if parent.name != "div":
            continue

        if len(parent.select('h3 a[href^="/google/"]')) > 1:
            break

        if parent.select_one('a[href$="/stargazers"]'):
            candidate = parent

    return candidate


conn = sqlite3.connect("google_repositories.db")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS repositories (
    name TEXT PRIMARY KEY,
    language TEXT,
    stars INTEGER
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS scrape_state (
    next_page INTEGER
)
""")

conn.commit()

state = cur.execute(
    "SELECT next_page FROM scrape_state"
).fetchone()

if state:
    page = state[0]

else:
    row = cur.execute("""
        SELECT MIN(rowid)
        FROM repositories
        WHERE rowid > 1200
        AND language = '不明'
    """).fetchone()[0]

    page = (row - 1) // 30 + 1 if row else 1

try:
    if page != 0:
        print(f"開始ページ: {page}")

        previous_names = set()

        while True:
            time.sleep(1)

            response = requests.get(
                url,
                params={"type": "all", "page": page},
                headers=headers,
                timeout=30
            )

            if response.status_code == 429:
                raise RuntimeError(
                    f"アクセス制限です。{page}ページから再実行してください。"
                )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.content,
                "html.parser"
            )

            if "No more repositories" in soup.get_text(" ", strip=True):
                print("最終ページまで取得しました")
                break

            repo_list = []
            names = set()

            for h3 in soup.find_all("h3"):
                link = h3.find("a", href=True)

                if link is None:
                    continue

                parts = link["href"].split("?")[0].strip("/").split("/")

                if len(parts) != 2 or parts[0].lower() != "google":
                    continue

                name = parts[1]
                card = get_card(h3)

                if card is None:
                    raise RuntimeError(
                        f"{page}ページ: {name} のHTML構造を確認してください"
                    )

                star_tag = None

                for a in card.select('a[href$="/stargazers"]'):
                    if a.get("href", "").strip("/").lower() == (
                        f"google/{name}/stargazers".lower()
                    ):
                        star_tag = a
                        break

                if star_tag is None:
                    raise RuntimeError(
                        f"{page}ページ: {name} のスター数を取得できません"
                    )

                star_text = star_tag.get("aria-label", "")

                match = re.search(
                    r"\d[\d,.]*[kKmM]?",
                    star_text
                )

                if match is None:
                    match = re.search(
                        r"\d[\d,.]*[kKmM]?",
                        star_tag.get_text(" ", strip=True)
                    )

                if match is None:
                    raise RuntimeError(
                        f"{page}ページ: {name} のスター数を読めません"
                    )

                value = match.group().replace(",", "").lower()

                if value.endswith("k"):
                    stars = round(float(value[:-1]) * 1000)

                elif value.endswith("m"):
                    stars = round(float(value[:-1]) * 1000000)

                else:
                    stars = int(value)

                language = get_language(card)

                repo_list.append((name, language, stars))
                names.add(name)

            if not repo_list:
                raise RuntimeError(
                    f"{page}ページ: データが0件です"
                )

            if names == previous_names:
                raise RuntimeError(
                    f"{page}ページ: 前ページと同じデータです"
                )

            previous_names = names

            lang_count = sum(
                language != "不明"
                for _, language, _ in repo_list
            )

            if lang_count == 0 and len(repo_list) >= 10:
                raise RuntimeError(
                    f"{page}ページ: 言語を取得できません"
                )

            for name, language, stars in repo_list:
                cur.execute("""
                    INSERT OR IGNORE INTO repositories
                    (name, language, stars)
                    VALUES (?, ?, ?)
                """, (name, language, stars))

                if language != "不明":
                    cur.execute("""
                        UPDATE repositories
                        SET language = ?, stars = ?
                        WHERE name = ?
                    """, (language, stars, name))

            cur.execute("DELETE FROM scrape_state")
            cur.execute(
                "INSERT INTO scrape_state VALUES (?)",
                (page + 1,)
            )

            conn.commit()

            print(
                f"{page}ページ: {len(repo_list)}件 / "
                f"言語取得 {lang_count}件"
            )

            page += 1

        cur.execute("DELETE FROM scrape_state")
        cur.execute("INSERT INTO scrape_state VALUES (0)")
        conn.commit()

    cur.execute("""
        SELECT name, language, stars
        FROM repositories
        ORDER BY name
    """)

    rows = cur.fetchall()

    for row in rows:
        print(row)

    with open(
        "google_repositories.csv",
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:
        writer = csv.writer(f)
        writer.writerow(["name", "language", "stars"])
        writer.writerows(rows)

    print("合計:", len(rows))

    print(
        "言語不明:",
        sum(language == "不明" for _, language, _ in rows)
    )

    print("CSV保存: google_repositories.csv")
    print("スクレイピングが完了しました")

finally:
    conn.close()
