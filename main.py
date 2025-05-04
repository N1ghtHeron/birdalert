#!/usr/bin/env python3
# coding: utf-8
"""
输入文件：
  ebird_taxonomy_intergrated.json：ebird的日本鸟种数据库，包含中文、英语、日语的常用名
  spot_zoopicker_latlng.csv：zoopicker东京前5页的观鸟热点，共129处，格式：pid,地点,纬度,经度
  ebird_world_life_list.csv：你的生涯列表，需包含【Scientific Name】。（请转换成 utf-8 格式）
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
import math
import matplotlib
matplotlib.use('Agg')  # 不用 X server
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import os
import re
import base64

# TODO：----------------------- local debug ----------------------------
# from dotenv import load_dotenv
# load_dotenv()
# ----------------------- 全局配置 ----------------------------
num_days = 3    # 最近几天数据
ebird_token = os.getenv("EBIRD_API_KEY")    # eBird API Token
center_lat = float(os.getenv("LAT"))   # 中心纬度（可用于地图背景中心）
center_lng = float(os.getenv("LNG"))   # 中心经度
dist = 40   # 搜索半径 (km)
lang = "zh_SIM"
url = f"/v2/data/obs/geo/recent?lat={center_lat}&lng={center_lng}&back={num_days}&dist={dist}&hotspot=true&sppLocale={lang}"
# 合并 mark 所用的地理距离阈值（单位：km），可自行调整，现转换为度数约 0.01
MERGE_DIST_THRESHOLD = 0.01
# ----------------------- 可选 ----------------------------
# 定义map需要绘制的参考点：每个是 (名称, 纬度, 经度, 颜色)
points = [
    ("东京", 35.68130519920022, 139.76696828540227, "orange"),
    ("新宿", 35.68961592626701, 139.70061774995483, "orange"),
    ("中野", 35.70580108800837, 139.6657665184044, "orange"),
    ("武藏境", 35.70214057743925, 139.5435792719855, "orange"),
    ("国分寺", 35.70024930597879, 139.48038908485745, "orange"),
    ("八王子", 35.655667733355955, 139.3389406289402, "orange"),
    ("船桥", 35.701772133562386, 139.98533416636502, "yellow"),
    # ("千叶", 35.61317547413481, 140.11302864291173, "yellow"),
    ("横滨", 35.46597321183, 139.62248127062082, "red"),
    ("浮间舟渡", 335.79120935252208, 139.69139132560102, "green"),
    ("登户", 35.620770639724874, 139.57013079209094, "yellow"),
    ("本川越", 35.913759602811986, 139.48101692413812, "cyan"),
    ("大森", 35.58844941186761, 139.7278648498221, "cyan"),
    ("柏", 35.86214724119525, 139.97092467249468, "cyan"),
    ("府中", 35.67220857368087, 139.48018184169294, "magenta"),
    ("高尾山口", 35.632317965327076, 139.27002597601265, "magenta"),
    ("桥本", 35.59495972805369, 139.3449777424018, "magenta"),
]
# ----------------------- 通用工具函数 ----------------------------
def clean_location(loc_str):
    """
    去除地点名称中括号及其后面的部分。
    例如： "千代田区--皇居--东御苑 (Chiyoda Ward--略)" -> "千代田区--皇居--东御苑"
    """
    return re.sub(r'\s*\(.*$', '', loc_str).strip()

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
    """
    加载观鸟地点列表 CSV，每条记录包含 页面URL、地点名称、纬度、经度
    如果 CSV 中不存在经纬度，则 lat, lng 作为 None 返回
    """
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
            location = row[1].strip() if len(row) > 1 else ""
            lat_val = float(row[2].strip()) if len(row) > 2 and row[2].strip() else None
            lng_val = float(row[3].strip()) if len(row) > 3 and row[3].strip() else None
            locs.append({
                "pid": pid,
                "url": f"https://zoopicker.com/places/{pid}/watcheds",
                "location": location,
                "lat": lat_val,
                "lng": lng_val,
            })
    return locs

# ----------------------- eBird 数据获取函数 ----------------------------
def fetch_ebird_data():
    """
    调用 eBird API 获取最近3天指定坐标 (center_lat, center_lng) 半径 dist 千米内的观测记录，
    返回按日期（格式化后的 "YYYY-MM-DD (星期X)"）和物种聚合的数据，
    除了统计数量，还保存每条记录的地点（locName）、数据来源及其坐标（如果有）
    """
    conn = http.client.HTTPSConnection("api.ebird.org")
    payload = ''
    headers = {
        'X-eBirdApiToken': ebird_token
    }
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
        # 尝试获取观测记录中的经纬度信息
        lat_obs = obs.get("lat", None)
        lng_obs = obs.get("lng", None)

        if formatted_date not in aggregated:
            aggregated[formatted_date] = {}
        if sci not in aggregated[formatted_date]:
            aggregated[formatted_date][sci] = {"total": 0, "locations": {}}
        aggregated[formatted_date][sci]["total"] += count
        # 用四元组保存：地点名称、来源、经纬度
        key = (loc, "ebird", lat_obs, lng_obs)
        aggregated[formatted_date][sci]["locations"][key] = aggregated[formatted_date][sci]["locations"].get(key, 0) + count
    return aggregated

# ----------------------- 数据聚合函数 ----------------------------
def aggregate_data():
    """
    聚合 zoopicker 与 eBird 数据，返回：
      aggregated：按日期和物种聚合的字典
      name_map：物种中文/日文映射
      locations：zoopicker 地点列表（包含经纬度信息）
    """
    location_csv = "data/spot_zoopicker_latlng.csv"
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

    aggregated = {}  # 聚合来自 zoopicker & eBird 的数据

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
                key = (loc["location"], "zoopicker")  # 此时 key 长度为 2
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
                # key 为四元组 (loc, "ebird", lat, lng)
                aggregated[date_key][sci]["locations"][key] = aggregated[date_key][sci]["locations"].get(key, 0) + cnt

    return aggregated, name_map, locations

# ----------------------- 生成 Markdown 文件 ----------------------------
def generate_markdown():
    aggregated, name_map, _ = aggregate_data()
    lines = [f"# 最近{num_days}天观测到但未收录的鸟种："]
    if not aggregated:
        lines.append("无新增鸟种记录。")
    else:
        for date_key in sorted(aggregated.keys(), reverse=True):
            lines.append(f"\n## {date_key}")
            for sci, data in sorted(aggregated[date_key].items()):
                total = data["total"]
                names = name_map.get(sci, {"chinese": "", "japanese": ""})
                cn = names.get("chinese", "")
                jp = names.get("japanese", "")
                lines.append(f"\n### {cn}，{jp}，{sci} ({total})")
                for key, cnt in sorted(data["locations"].items()):
                    # key 可能为 (loc, source) 或 (loc, source, lat, lng)
                    loc_text = key[0]
                    # 清洗地点名称
                    loc_text = clean_location(loc_text)
                    source = key[1]
                    lines.append(f"- {loc_text} ({cnt}, {source})")
    md_text = "\n".join(lines)
    return md_text

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

# ----------------------- 生成地图图片 ----------------------------
def generate_map():
    """
    根据聚合数据生成地图图片：
      1. 使用正确的经纬度比例绘制
      2. 使用特殊 marker 绘制数据点
      3. 适配日文显示（请确保系统中已安装支持日文的字体，如 "Noto Sans CJK JP"）
      4. 动态计算边界（经纬度精度达到小数点5位）
      5. 在地图上以 cross marker 标记中心点
    """
    font_path = os.path.join(os.path.dirname(__file__), "fonts", "STHeiti Medium.ttc")
    fm.fontManager.addfont(font_path)
    jp_font = fm.FontProperties(fname=font_path)
    plt.rcParams["font.family"] = jp_font.get_name()
    plt.rcParams["axes.unicode_minus"] = False

    # 获取聚合数据（aggregate_data() 需已定义）
    aggregated, name_map, location_list = aggregate_data()

    # 构造 marker 数据，每个 marker 包含：
    # "lat", "lng": 坐标
    # "birds": 收集鸟种记录，字符串格式 "鸟种,数量,月日,来源"
    # "locations": 收集地点名称（集合），用于显示在第一行的注释
    raw_markers = []
    for date_key, species_data in aggregated.items():
        try:
            # 例如转换 "2025-04-28 (星期二)" 成 "4/28"
            mm_dd = datetime.datetime.strptime(date_key.split()[0], "%Y-%m-%d").strftime("%-m/%-d")
        except Exception:
            mm_dd = date_key
        for sci, data in species_data.items():
            names = name_map.get(sci, {"chinese": ""})
            cn = names.get("chinese", "")
            for loc_key, cnt in data["locations"].items():
                loc_name = loc_key[0]
                source = loc_key[1]
                lat_marker = None
                lng_marker = None
                if source == "zoopicker":
                    for rec in location_list:
                        if rec["location"] == loc_name:
                            lat_marker = rec.get("lat")
                            lng_marker = rec.get("lng")
                            break
                elif source == "ebird":
                    lat_marker = loc_key[2]
                    lng_marker = loc_key[3]
                if lat_marker is None or lng_marker is None:
                    continue
                # 构造该条记录文本（不含地点名称）
                text_line = f"{cn},{cnt},{mm_dd},{source}"
                raw_markers.append({
                    "lat": lat_marker,
                    "lng": lng_marker,
                    "birds": [text_line],
                    "locations": {loc_name}
                })

    print(f"调试输出：共收集到 {len(raw_markers)} 个原始 marker")

    # 合并相近 marker：合并时合并鸟种记录列表与地点名称集合
    merged_markers = []
    for m in raw_markers:
        merged = False
        for exist in merged_markers:
            d = math.sqrt((m["lat"] - exist["lat"])**2 + (m["lng"] - exist["lng"])**2)
            if d < MERGE_DIST_THRESHOLD:
                # 加权求中心（权重使用此 marker 的原始观测总数，可用鸟种记录数量累加代替，有时一条记录可能已包含多只鸟）
                total_weight = len(exist["birds"]) + len(m["birds"])
                exist["lat"] = (exist["lat"] * len(exist["birds"]) + m["lat"] * len(m["birds"])) / total_weight
                exist["lng"] = (exist["lng"] * len(exist["birds"]) + m["lng"] * len(m["birds"])) / total_weight
                exist["birds"].extend(m["birds"])
                exist["locations"].update(m["locations"])
                merged = True
                break
        if not merged:
            merged_markers.append(m)
    print(f"调试输出：合并后共 {len(merged_markers)} 个 marker")

    # 定义根据 marker 中不同鸟种数量选择颜色的函数
    def get_marker_color(marker):
        species_set = set()
        for rec in marker["birds"]:
            # 假设 rec 格式为 "鸟种,数量,月日,来源"，取第1个字段为鸟种
            species = rec.split(",")[0].strip()
            if species:
                species_set.add(species)
        species_count = len(species_set)
        if species_count < 2:
            return "blue"
        elif species_count < 4:
            return "green"
        elif species_count < 6:
            return "orange"
        else:
            return "red"

    # 动态计算边界，计算所有 marker 的经纬度范围，以5位小数显示
    if merged_markers:
        lons = [m["lng"] for m in merged_markers]
        lats = [m["lat"] for m in merged_markers]
        lon_min = math.floor(min(lons) * 1e5) / 1e5
        lon_max = math.ceil(max(lons) * 1e5) / 1e5
        lat_min = math.floor(min(lats) * 1e5) / 1e5
        lat_max = math.ceil(max(lats) * 1e5) / 1e5
        margin = 0.001  # 可调整边缘空白
        lon_min -= margin
        lon_max += margin
        lat_min -= margin
        lat_max += margin
    else:
        lon_min, lon_max = center_lng - 0.2, center_lng + 0.2
        lat_min, lat_max = center_lat - 0.2, center_lat + 0.2

    fig, ax = plt.subplots(figsize=(10, 8))
    # 绘制 marker 数据点，特殊 marker "*" 表示这些点
    for marker in merged_markers:
        color = get_marker_color(marker)
        ax.scatter(marker["lng"], marker["lat"], c=color, s=100, alpha=0.8,
                   edgecolors='none', marker="*")
        # 构造标注文本：
        # 第一行显示所有地点名称（以逗号连接，使用和 marker 相同颜色），
        # 后续每行显示鸟种记录。
        # 对于标注，第一行显示所有地点名称（清洗后），后续显示鸟种记录
        loc_names = "、".join([clean_location(name) for name in marker["locations"]])
        details = "\n".join(marker["birds"])
        annotation = f"{loc_names}\n{details}"
        ax.text(marker["lng"] + 0.0005, marker["lat"] + 0.0005, annotation,
                fontsize=10, color=color, fontproperties=jp_font)

    # 绘制
    for name, lat, lng, color in points:
        ax.scatter(x=lng, y=lat, marker="x", c=color, s=100, linewidths=2)
        ax.text(lng + 0.0005, lat + 0.0005, name, fontsize=10, color="black", fontproperties=jp_font)

    # 画圆：以 center_lng, center_lat 为圆心，dist(km) 作为半径
    radius_lat = dist / 111.0
    radius_lng = dist / (111.0 * math.cos(center_lat * math.pi / 180))
    theta = np.linspace(0, 2 * np.pi, 100)
    circle_lng = center_lng + radius_lng * np.cos(theta)
    circle_lat = center_lat + radius_lat * np.sin(theta)
    ax.plot(circle_lng, circle_lat, color="gray", linestyle="--", linewidth=1.5, label="搜索范围")

    ax.set_xlabel("经度", fontproperties=jp_font)
    ax.set_ylabel("緯度", fontproperties=jp_font)
    # ax.set_title(f"最近{num_days}天観測地点统计", fontproperties=jp_font)
    ax.set_xlim(lon_min-0.1, lon_max+0.1)
    ax.set_ylim(lat_min-0.1, lat_max+0.1)
    ax.set_aspect("equal", adjustable="box")
    ax.legend(prop=jp_font)
    plt.tight_layout()
    export_dir = "export"
    os.makedirs(export_dir, exist_ok=True)
    map_path = os.path.join(export_dir, "markers_map.png")
    plt.savefig(map_path, dpi=150)
    plt.close()
    print(f"地图图片已生成：{map_path}")


def combine_markdown_and_map(markdown_file, map_file):
    """
    读取 Markdown 文件，并构造一个图片链接指向已上传的地图图片。
    假设地图图片已经通过 git commit 上传到了主分支的 export 文件夹下。
    """
    with open(markdown_file, "r", encoding="utf-8") as f:
        md_text = f.read()

    # 从环境变量中获取仓库路径，例如 "username/repo"
    repo_full = os.getenv("GITHUB_REPOSITORY", "USER/REPO")
    # 构造图片链接（注意分支名称需与实际一致，这里假设为 main 分支）
    image_url = f"https://raw.githubusercontent.com/{repo_full}/main/export/markers_map.png"
    image_md = f"![地图]({image_url})"

    combined_md = md_text + "\n\n" + image_md
    return combined_md


def create_github_issue_with_map():
    """
    生成 Markdown 与地图，并将合并后的结果作为 Issue 正文提交。
    """
    import os, datetime
    date_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    # 生成 Markdown 文件
    md_text = generate_markdown()
    md_path = os.path.join("export", f"{date_str}.md")
    write_markdown_to_file(md_text, date_str)

    # 生成地图图片
    generate_map()  # 此函数会在 export 文件夹下生成 markers_map.png

    # 指定地图文件路径
    map_path = os.path.join("export", "markers_map.png")
    if not os.path.isfile(map_path):
        print("错误：找不到地图图片文件。")
        return

    # 合并 Markdown 和地图图片
    combined_body = combine_markdown_and_map(md_path, map_path)

    # 使用 GitHub API 创建 Issue（create_github_issue() 已经定义）
    create_github_issue(combined_body, date_str)

# ----------------------- Main ----------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        nargs="+",
        choices=["generate", "create-issue", "generate-map", "issue-with-map"],
        default=["generate"],
        help="运行模式：generate(生成 Markdown), create-issue(根据 Markdown 创建 GitHub Issue), generate-map(生成地图图片), issue-with-map(合并 Markdown 和地图后提交 Issue)"
    )
    args = parser.parse_args()

    date_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    if "generate" in args.mode:
        md = generate_markdown()
        write_markdown_to_file(md, date_str)
        print(md)

    if "generate-map" in args.mode:
        generate_map()

    if "create-issue" in args.mode:
        # 仅提交纯 Markdown 创建 Issue
        md_path = os.path.join("export", f"{date_str}.md")
        if not os.path.isfile(md_path):
            print(f"Error: 找不到 Markdown 文件 {md_path}，请先运行 --mode generate。")
        else:
            with open(md_path, encoding="utf-8") as f:
                body = f.read()
            create_github_issue(body, date_str)

    if "issue-with-map" in args.mode:
        create_github_issue_with_map()
