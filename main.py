#!/usr/bin/env python3
# coding: utf-8
"""
input files:
ebird_taxonomy_intergrated.json：eBird 三种语言的鸟种数据库，详见 tools/get_taxonomy
spot_zoopicker.csv：zoopicker东京前5页的观鸟地，去掉了三宅岛附近以及多摩動物公園，共129处
ebird_world_life_list.csv：自己的生涯列表，ebird个人页面可以下载csv，注意可能需要转换成utf-8格式
"""

import os
import argparse
import datetime
import requests
from bs4 import BeautifulSoup
import csv
from datetime import timedelta
from github import Github
import json
import http.client

# TODO：----------------------- local debug ----------------------------
# from dotenv import load_dotenv
# load_dotenv()
# ----------------------- 全局配置 ----------------------------
num_days = 3    # 最近几天数据
ebird_token = os.getenv("EBIRD_API_KEY")    # eBird API Token
lat = float(os.getenv("LAT"))   # center location
lng = float(os.getenv("LNG"))
dist = 40   # radius distance (km)
lang = "zh_SIM"
url = f"/v2/data/obs/geo/recent?lat={lat}&lng={lng}&back={num_days}&dist={dist}&hotspot=true&sppLocale={lang}"

# ----------------------- 通用工具函数 ----------------------------
def get_cn_week_map():
    return {0:"星期一", 1:"星期二", 2:"星期三", 3:"星期四", 4:"星期五", 5:"星期六", 6:"星期日"}

def format_date(date_str):
    # date_str 格式: "YYYY-MM-DD"
    d = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    week = get_cn_week_map()
    return f"{d.strftime('%Y-%m-%d')} ({week[d.weekday()]})"

def get_target_dates(num_days=num_days):
    dates = set()
    today = datetime.datetime.now()
    for i in range(num_days):
        d = today - timedelta(days=i)
        dates.add(d.date())
    return dates

def fetch_page(url):
    """获取指定 URL 页面的 HTML 内容"""
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

def parse_records_jp(html, target_date_mapping):
    """
    解析 zoopicker 日语页面中的记录，
    返回按页面中日期（target_date_mapping 的 key）分组的记录字典
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    records_by_date = {}
    for i, line in enumerate(lines):
        if line in target_date_mapping:
            if i >= 2:
                observed_jp = lines[i - 2]
                mid = lines[i - 1]
                parts = mid.split("/")
                sci = parts[1].strip() if len(parts) > 1 else ""
                rec = {"observed_jp": observed_jp, "scientific": sci}
                records_by_date.setdefault(line, []).append(rec)
    return records_by_date

def load_library(csv_file):
    """加载已收录鸟种 CSV，返回已收录鸟种的 set（以科学名称为 key）"""
    library = set()
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sci = row.get("Scientific Name", "").strip()
            if sci:
                library.add(sci)
    return library

def load_mapping(json_file):
    """
    从整合后的 JSON 文件加载物种映射，
    返回一个以科学名称为 key，对应中文（comName_zh_SIM）和日文（comName_ja）的字典
    """
    mapping = {}
    with open(json_file, encoding='utf-8') as f:
        data = json.load(f)
        for item in data:
            latin = item.get("sciName", "").strip()
            chinese = item.get("comName_zh_SIM", "").strip()
            japanese = item.get("comName_ja", "").strip()
            if latin:
                mapping[latin] = {"chinese": chinese, "japanese": japanese}
    return mapping

def load_locations(csv_file):
    """加载观鸟地点列表 CSV，每条记录包含页面 URL 和地点名称"""
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

# ----------------------- eBird 数据获取函数 ----------------------------
def fetch_ebird_data():
    """
    调用 eBird API 获取最近3天指定坐标 (lat,lng) 半径 dist 千米内区域的观测记录，
    返回按日期（格式化后的 "YYYY-MM-DD (星期X)"）和物种聚合的数据，
    数据中记录每个物种的总数量和各地点（来源标记为 ebird）的数量
    """

    conn = http.client.HTTPSConnection("api.ebird.org")
    payload = ''
    headers = {
        'X-eBirdApiToken': ebird_token
    }
    # 获取最近 3 天的数据，使用 sppLocale=zh_SIM 返回中文常用名（如果支持）
    conn.request("GET", url, payload, headers)
    res = conn.getresponse()
    data = res.read()
    if res.status != 200:
        print(f"Error: Received status code {res.status}")
        return {}
    try:
        observations = json.loads(data.decode("utf-8"))
    except Exception as e:
        print("解析 eBird 响应 JSON 出错：", e)
        return {}

    aggregated = {}
    target_dates = get_target_dates()
    for obs in observations:
        # obsDt 格式："YYYY-MM-DD HH:MM"
        obs_date_str = obs.get("obsDt", "").split()[0]
        try:
            obs_date = datetime.datetime.strptime(obs_date_str, "%Y-%m-%d").date()
        except:
            continue
        if obs_date not in target_dates:
            continue
        formatted_date = format_date(obs_date_str)
        sci = obs.get("sciName", "").strip()
        if not sci:
            continue
        count = obs.get("howMany", 1)
        loc = obs.get("locName", "").strip()

        if formatted_date not in aggregated:
            aggregated[formatted_date] = {}
        if sci not in aggregated[formatted_date]:
            aggregated[formatted_date][sci] = {"total": 0, "locations": {}}
        aggregated[formatted_date][sci]["total"] += count
        key = (loc, "ebird")
        aggregated[formatted_date][sci]["locations"][key] = aggregated[formatted_date][sci]["locations"].get(key, 0) + count
    return aggregated

# ----------------------- 报告聚合与生成 ----------------------------
def generate_markdown():
    # 定义文件路径（请根据实际情况修改）
    location_csv = "data/spot_zoopicker.csv"
    library_csv = "data/ebird_world_life_list.csv"
    mapping_json = "data/ebird_taxonomy_integrated.json"

    # 构造 zoopicker 页面中日期映射，页面日期格式例如 "2025年4月20日(日)に観察"
    target_map = {}
    today = datetime.datetime.now()
    jp_week_map = {0:"月", 1:"火", 2:"水", 3:"木", 4:"金", 5:"土", 6:"日"}
    cn_week_map = get_cn_week_map()
    for i in range(num_days):
        d = today - timedelta(days=i)
        jp_key = f"{d.year}年{d.month}月{d.day}日({jp_week_map[d.weekday()]})に観察"
        cn_key = f"{d.strftime('%Y-%m-%d')} ({cn_week_map[d.weekday()]})"
        target_map[jp_key] = cn_key

    library = load_library(library_csv)
    name_map = load_mapping(mapping_json)
    locations = load_locations(location_csv)

    aggregated = {}  # 聚合来自 zoopicker & eBird 两种数据

    # 聚合 zoopicker 数据，标记数据来源为 "zoopicker"
    for loc in locations:
        try:
            html = fetch_page(loc["url"])
        except Exception as e:
            print(f"获取 {loc['location']} 页面失败：{e}")
            continue
        recs = parse_records_jp(html, target_map)
        for jp_date, rec_list in recs.items():
            out_date = target_map[jp_date]
            for rec in rec_list:
                sci = rec["scientific"]
                if not sci or sci in library:
                    continue
                if out_date not in aggregated:
                    aggregated[out_date] = {}
                if sci not in aggregated[out_date]:
                    aggregated[out_date][sci] = {"total": 0, "locations": {}}
                aggregated[out_date][sci]["total"] += 1  # 默认计数1
                key = (loc["location"], "zoopicker")
                aggregated[out_date][sci]["locations"][key] = aggregated[out_date][sci]["locations"].get(key, 0) + 1

    # 聚合 eBird 数据（来源标记 "ebird"）
    ebird_data = fetch_ebird_data()
    for date_key, species_data in ebird_data.items():
        if date_key not in aggregated:
            aggregated[date_key] = {}
        for sci, data in species_data.items():
            if sci in library:
                continue
            if sci not in aggregated[date_key]:
                aggregated[date_key][sci] = {"total": 0, "locations": {}}
            aggregated[date_key][sci]["total"] += data["total"]
            for key, cnt in data["locations"].items():
                aggregated[date_key][sci]["locations"][key] = aggregated[date_key][sci]["locations"].get(key, 0) + cnt

    # 构建 Markdown 内容
    lines = [f"# 最近{num_days}天观测到但未收录的鸟种："]
    if not aggregated:
        lines.append("无新增鸟种记录。")
    else:
        for date_key in sorted(aggregated.keys(), reverse=True):
            lines.append(f"\n## {date_key}")
            for sci, data in sorted(aggregated[date_key].items()):
                total = data["total"]
                # 通过映射字典获取物种中文和日文名称
                names = name_map.get(sci, {"chinese": "", "japanese": ""})
                cn = names.get("chinese", "")
                jp = names.get("japanese", "")
                lines.append(f"\n### {cn}，{jp}，{sci} ({total})")
                for (loc, source), cnt in sorted(data["locations"].items()):
                    lines.append(f"- {loc} ({cnt}, {source})")
    return "\n".join(lines)

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

# ----------------------- Main ----------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--mode", choices=["generate", "create-issue"], required=True,
                        help="运行模式: generate(生成 Markdown), create-issue(根据 Markdown 创建 GitHub Issue)")

    # TODO：----------------------- local debug 则改成 ----------------------------
    # parser.add_argument("--mode", choices=["generate", "create-issue"],
    #                     default="generate",  # 设置默认模式
    #                     help="运行模式: generate(生成 Markdown), create-issue(根据 Markdown 创建 GitHub Issue)")

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

