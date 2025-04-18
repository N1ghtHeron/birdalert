# coding: utf-8
"""
main.py

Modes:
  --mode generate      Generate markdown file under export/YYYY-MM-DD.md
  --mode create-issue  Create a GitHub issue from the markdown file

Dependencies:
  pip install requests beautifulsoup4 PyGithub
"""
import os
import argparse
import datetime
import requests
from bs4 import BeautifulSoup
import csv
from datetime import timedelta
from github import Github

# Number of days to look back
num_days = 3

#--------- Existing utility functions ----------
def fetch_page(url):
    """
    获取指定 URL 的页面内容，设置合适的 User-Agent 避免被拒绝。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/105.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.text


def get_target_date_mapping(num_days=num_days):
    """
    生成最近 num_days 天的目标日期映射。
    """
    jp_week_map = {0: "月", 1: "火", 2: "水", 3: "木", 4: "金", 5: "土", 6: "日"}
    cn_week_map = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日"}

    mapping = {}
    today = datetime.datetime.now()
    for i in range(num_days):
        d = today - timedelta(days=i)
        jp = f"{d.year}年{d.month}月{d.day}日({jp_week_map[d.weekday()]})に観察"
        cn = f"{d.strftime('%Y-%m-%d')} ({cn_week_map[d.weekday()]})"
        mapping[jp] = cn
    return mapping


def parse_records_jp(html, target_date_mapping):
    """
    解析日语页面中的鸟种记录。
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    records_by_date = {}
    for i, line in enumerate(lines):
        if line in target_date_mapping:
            if i >= 2:
                observed_jp = lines[i-2]
                mid = lines[i-1]
                parts = mid.split("/")
                sci = parts[1].strip() if len(parts) > 1 else ""
                rec = {"observed_jp": observed_jp, "scientific": sci}
                records_by_date.setdefault(line, []).append(rec)
    return records_by_date


def load_library(csv_file):
    library = set()
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sci = row.get("Scientific Name", "").strip()
            if sci:
                library.add(sci)
    return library


def load_mapping(csv_file):
    mapping = {}
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or all(not c.strip() for c in row):
                continue
            if row[0].strip() == "English Name":
                continue
            if len(row) < 3:
                continue
            latin = row[1].strip()
            chinese = row[2].strip()
            mapping[latin] = {"chinese": chinese, "japanese": ""}
    return mapping


def load_locations(csv_file):
    locs = []
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or all(not c.strip() for c in row):
                continue
            pid = row[0].strip()
            try:
                int(pid)
            except ValueError:
                continue
            locs.append({
                "url": f"https://zoopicker.com/places/{pid}/watcheds",
                "location": row[1].strip() if len(row) > 1 else ""
            })
    return locs

#--------- Core logic to aggregate and generate markdown ----------
def generate_markdown():
    # Load data sources
    location_csv = "data/spot_zoopicker.csv"
    library_csv = "data/ebird_world_life_list.csv"
    mapping_csv = "data/Avibase_Tokyo.csv"

    locations = load_locations(location_csv)
    target_map = get_target_date_mapping()
    library = load_library(library_csv)
    name_map = load_mapping(mapping_csv)

    # Collect missing records
    results = {}
    for loc in locations:
        try:
            html = fetch_page(loc["url"])
        except Exception as e:
            print(f"获取 {loc['location']} 页面失败：", e)
            continue
        recs = parse_records_jp(html, target_map)
        for jp_date, rec_list in recs.items():
            out_date = target_map[jp_date]
            missing = [r for r in rec_list if r["scientific"] and r["scientific"] not in library]
            if missing:
                results.setdefault(out_date, {}).setdefault(loc["location"], []).extend(missing)

    # Aggregate
    aggregated = {}
    for date_key, locs in results.items():
        aggregated.setdefault(date_key, {})
        for loc_name, rec_list in locs.items():
            for rec in rec_list:
                sci = rec["scientific"]
                entry = aggregated[date_key].get(sci, {"total": 0, "observed_jp": rec["observed_jp"], "locations": {}})
                entry["total"] += 1
                entry["locations"][loc_name] = entry["locations"].get(loc_name, 0) + 1
                aggregated[date_key][sci] = entry

    # Build markdown
    lines = [f"# 最近{num_days}天中观测到但未收录的鸟种："]
    if not aggregated:
        lines.append("无新增鸟种记录。")
    else:
        for date_key in sorted(aggregated.keys(), reverse=True):
            lines.append(f"\n## {date_key}")
            for sci, data in sorted(aggregated[date_key].items()):
                total = data["total"]
                cn = name_map.get(sci, {}).get("chinese", "")
                jp = name_map.get(sci, {}).get("japanese") or data["observed_jp"]
                lines.append(f"\n### {cn}，{jp}，{sci} ({total})")
                for loc_name, cnt in sorted(data["locations"].items()):
                    lines.append(f"- {loc_name} ({cnt})")

    return "\n".join(lines)

#--------- Helper for file writing and GitHub Issue creation ----------
def write_markdown_to_file(text, date_str):
    export_dir = "export"
    os.makedirs(export_dir, exist_ok=True)
    path = os.path.join(export_dir, f"{date_str}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Markdown file written to: {path}")


def create_github_issue(body, date_str):
    token = os.environ.get("TOKEN")
    if not token:
        print("Error: TOKEN 环境变量未设置。无法创建 Issue。")
        return
    repo_name = os.environ.get("GITHUB_REPOSITORY")
    if not repo_name:
        print("Error: GITHUB_REPOSITORY 环境变量未找到。")
        return
    gh = Github(token)
    repo = gh.get_repo(repo_name)
    title = f"每日报告 - {date_str}"
    issue = repo.create_issue(title=title, body=body)
    print(f"Issue created: {issue.html_url}")

#--------- Main Entry Point ----------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["generate", "create-issue"], required=True,
                        help="运行模式: generate(生成 Markdown), create-issue(创建 GitHub Issue)")
    args = parser.parse_args()

    date_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    if args.mode == "generate":
        md = generate_markdown()
        write_markdown_to_file(md, date_str)
        print(md)

    elif args.mode == "create-issue":
        path = os.path.join("export", f"{date_str}.md")
        if not os.path.isfile(path):
            print(f"Error: 找不到 Markdown 文件 {path}，请先运行 --mode generate。")
        else:
            with open(path, encoding="utf-8") as f:
                body = f.read()
            create_github_issue(body, date_str)
