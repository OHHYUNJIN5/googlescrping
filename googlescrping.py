import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import re

url = "https://github.com/orgs/google/repositories"
headers = {"User-Agent": "Mozilla/5.0"}

conn = sqlite3.connect("google_repositories.db")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS repositories (
    name TEXT PRIMARY KEY,
    language TEXT,
    stars INTEGER
)
""")
conn.commit()

cur.execute("SELECT COUNT(*) FROM repositories")
saved_count = cur.fetchone()[0]

page = 81

print(f"開始ページ: {page} / DB保存済み: {saved_count}件")

previous_names = set()

try:
    while True:
        response = None

        for attempt in range(3):
            time.sleep(1)

            try:
                response = requests.get(
                    url,
                    params={"type": "all", "page": page},
                    headers=headers,
                    timeout=30
                )
                response.raise_for_status()
                break

            except requests.RequestException as e:
                print(f"{page}ページ: 通信エラー ({e})")

                if attempt == 2:
                    raise

                time.sleep(5)

        soup = BeautifulSoup(response.content, "html.parser")
        text = soup.get_text(" ", strip=True)

        if "No more repositories." in text:
            print(f"{page}ページ: 最終ページの次に到達しました")
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
            star_tag = None
            card = None

            for parent in h3.parents:
                if parent.name not in ("li", "article", "div"):
                    continue

                for a in parent.select('a[href$="/stargazers"]'):
                    if a.get("href", "").strip("/").lower() == f"google/{name}/stargazers".lower():
                        star_tag = a
                        card = parent
                        break

                if star_tag is not None:
                    break

            if star_tag is None:
                raise RuntimeError(
                    f"{page}ページ: {name} のスター数が見つかりません"
                )

            language_tag = card.find(
                attrs={"itemprop": "programmingLanguage"}
            )

            if language_tag is None:
                language_tag = card.select_one(
                    '[data-testid="repository-language"]'
                )

            if language_tag is None:
                dot = card.select_one(".repo-language-color")

                if dot is not None:
                    language_tag = dot.find_next_sibling("span")

            language = (
                language_tag.get_text(strip=True)
                if language_tag else "不明"
            )

            star_text = star_tag.get("aria-label", "")

            match = re.search(r"\d[\d,.]*[kKmM]?", star_text)

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

            repo_list.append((name, language, stars))
            names.add(name)

        if not repo_list:
            raise RuntimeError(
                f"{page}ページ: データが0件です (URL: {response.url})"
            )

        if names == previous_names:
            raise RuntimeError(
                f"{page}ページ: 前ページと同じデータです"
            )

        previous_names = names

        for name, language, stars in repo_list:
            cur.execute("""
                INSERT OR REPLACE INTO repositories
                (name, language, stars)
                VALUES (?, ?, ?)
            """, (name, language, stars))

        conn.commit()

        cur.execute("SELECT COUNT(*) FROM repositories")
        count = cur.fetchone()[0]

        print(
            f"{page}ページ: {len(repo_list)}件取得 / DB合計 {count}件"
        )

        page += 1

    cur.execute("""
        SELECT name, language, stars
        FROM repositories
        ORDER BY name
    """)

    for row in cur.fetchall():
        print(row)

    cur.execute("SELECT COUNT(*) FROM repositories")
    count = cur.fetchone()[0]

    print("合計:", count)

    print("スクレイピングが完了しました")

finally:
    conn.close()