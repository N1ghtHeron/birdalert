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
import csv
from datetime import timedelta
from github import Github
import json
import time  # 引入time用于API请求间隔，避免速率限制
from dotenv import load_dotenv
from zoopicker_client import (
    BASE_DIR, JST, TIMEOUT, ZoopickerClient, ZoopickerError,
    load_locations, parse_records_jp,
)

load_dotenv(BASE_DIR / ".env")  # Existing environment variables take precedence.
# ----------------------- 全局配置 ----------------------------
num_days = 3  # 最近几天数据
dist = 40  # radius distance (km)
lang = "zh_SIM"

# 基础URL模板
base_url = "https://api.ebird.org/v2/data/obs/geo/recent"


# ----------------------- 通用工具函数 ----------------------------
def get_cn_week_map():
    return {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日"}


def format_date(date_str):
    # date_str 格式: "YYYY-MM-DD"
    d = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    week = get_cn_week_map()
    return f"{d.strftime('%Y-%m-%d')} ({week[d.weekday()]})"


def get_target_dates(num_days=num_days, today=None):
    dates = set()
    today = today or datetime.datetime.now(JST).date()
    for i in range(num_days):
        d = today - timedelta(days=i)
        dates.add(d)
    return dates


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


# ----------------------- eBird 数据获取函数 (修改版) ----------------------------
def fetch_ebird_data(library_set, days=num_days, today=None, warnings=None):
    """
    1. 获取区域内所有近期出现的鸟种。
    2. 筛选出不在 library_set (Life List) 中的目标鸟种。
    3. 针对每个目标鸟种，调用 specific species 接口获取所有记录。
    """
    warnings = warnings if warnings is not None else []
    token = os.getenv("EBIRD_API_KEY")
    if not token:
        raise ValueError("eBird 缺少 EBIRD_API_KEY。")
    try:
        lat = float(os.getenv("LAT", ""))
        lng = float(os.getenv("LNG", ""))
    except ValueError:
        raise ValueError("请填写有效的 LAT（纬度）和 LNG（经度）。") from None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError("LAT 或 LNG 超出有效范围。")
    headers = {'X-eBirdApiToken': token}

    # 步骤 1: 获取概览，找出有哪些鸟
    # 使用 requests 替代 http.client，处理参数更方便
    params_overview = {
        'lat': lat,
        'lng': lng,
        'back': days,
        'dist': dist,
        'hotspot': 'true',
        'sppLocale': lang
    }

    try:
        print("正在获取 eBird 区域概览数据...")
        resp = requests.get(base_url, headers=headers, params=params_overview, timeout=TIMEOUT)
        resp.raise_for_status()
        overview_list = resp.json()
    except (requests.RequestException, ValueError):
        raise ValueError("eBird 概览请求失败或响应无效。") from None
    if not isinstance(overview_list, list):
        raise ValueError("eBird 概览响应结构变化。")

    # 步骤 2: 筛选出目标鸟种的代码 (speciesCode)
    target_species_codes = set()
    for obs in overview_list:
        sci_name = obs.get("sciName", "").strip()
        # 如果科学名不在 library 中，且有对应的 speciesCode
        if sci_name and sci_name not in library_set:
            code = obs.get("speciesCode")
            if code:
                target_species_codes.add(code)

    print(f"发现 {len(target_species_codes)} 种未收录鸟种，正在获取详细记录...")

    # 步骤 3: 针对每个目标鸟种获取详细记录并聚合
    aggregated = {}
    target_dates = get_target_dates(days, today)

    for idx, code in enumerate(target_species_codes):
        # 简单限流，防止请求过快 (可选)
        if idx > 0 and idx % 10 == 0:
            time.sleep(1)

        species_url = f"{base_url}/{code}"
        # 参数与概览相同，但针对特定物种会返回列表
        try:
            r = requests.get(species_url, headers=headers, params=params_overview, timeout=TIMEOUT)
            if r.status_code != 200:
                warnings.append(f"eBird 物种 {code} 请求失败（HTTP {r.status_code}）。")
                continue
            observations = r.json()
            if not isinstance(observations, list):
                raise ValueError("invalid observations")
        except (requests.RequestException, ValueError):
            warnings.append(f"eBird 物种 {code} 请求失败或响应无效。")
            continue

        # 处理该物种的所有记录
        for obs in observations:
            obs_date_str = obs.get("obsDt", "").split()[0]  # "YYYY-MM-DD HH:MM" -> "YYYY-MM-DD"
            try:
                obs_date = datetime.datetime.strptime(obs_date_str, "%Y-%m-%d").date()
            except:
                continue

            # 过滤日期
            if obs_date not in target_dates:
                continue

            formatted_date = format_date(obs_date_str)
            sci = obs.get("sciName", "").strip()
            count = obs.get("howMany", 1)  # 有些记录可能没有数量，默认为1
            if count is None: count = 1
            loc = obs.get("locName", "").strip()
            checklist_id = obs.get("subId", "").strip()
            checklist_url = f"https://ebird.org/checklist/{checklist_id}" if checklist_id else ""

            if formatted_date not in aggregated:
                aggregated[formatted_date] = {}
            if sci not in aggregated[formatted_date]:
                aggregated[formatted_date][sci] = {"total": 0, "locations": {}}

            aggregated[formatted_date][sci]["total"] += count

            # 聚合地点：eBird 记录保留 checklist URL，避免同地点不同清单被合并丢失链接
            key = (loc, "ebird", checklist_url)
            aggregated[formatted_date][sci]["locations"][key] = aggregated[formatted_date][sci]["locations"].get(key,
                                                                                                                 0) + count

    return aggregated


# ----------------------- 报告聚合与生成 ----------------------------
def generate_markdown(*, zoopicker_only=False, place_ids=None, days=num_days, today=None):
    # 定义文件路径（请根据实际情况修改）
    if days < 1:
        raise ValueError("days 必须大于 0。")
    location_csv = BASE_DIR / "data/spot_zoopicker.csv"
    library_csv = BASE_DIR / "data/ebird_world_life_list.csv"
    mapping_json = BASE_DIR / "data/ebird_taxonomy_integrated.json"
    target_dates = get_target_dates(days, today)

    library = load_library(library_csv)
    name_map = load_mapping(mapping_json)
    locations = load_locations(location_csv)
    if place_ids is not None:
        known = {loc["id"] for loc in locations}
        unknown = set(place_ids) - known
        if unknown:
            raise ValueError(f"地点不在配置列表中：{', '.join(map(str, sorted(unknown)))}")
        locations = [loc for loc in locations if loc["id"] in place_ids]

    aggregated = {}  # 聚合来自 zoopicker & eBird 两种数据

    warnings = []
    completed = 0
    try:
        with ZoopickerClient.from_env() as client:
            print("Zoopicker 登录已验证。")
            for loc in locations:
                result = client.fetch_place(loc["id"], target_dates)
                if result.warning:
                    warnings.append(f"Zoopicker {loc['location']}：{result.warning}")
                else:
                    completed += 1
                print(f"Zoopicker {loc['location']}：{result.pages} 页，"
                      f"{result.fetched_count} 条原始记录，{len(result.records)} 条在日期范围内，"
                      f"{'不完整' if result.warning else '完成'}。")
                for rec in result.records:
                    sci = rec.scientific
                    if sci in library:
                        continue
                    out_date = format_date(rec.date.isoformat())
                    if out_date not in aggregated:
                        aggregated[out_date] = {}
                    if sci not in aggregated[out_date]:
                        aggregated[out_date][sci] = {"total": 0, "locations": {}}
                    aggregated[out_date][sci]["total"] += 1
                    key = (loc["location"], "zoopicker", loc["place_url"])
                    aggregated[out_date][sci]["locations"][key] = aggregated[out_date][sci]["locations"].get(key, 0) + 1
                if not client.authenticated:
                    warnings.append("Zoopicker 登录无法恢复，剩余地点未完成抓取。")
                    break
    except ZoopickerError as error:
        warnings.append(f"Zoopicker：{error}")

    # 聚合 eBird 数据（修改点：传入 library 用于内部筛选和二次查询）
    # 注意：fetch_ebird_data 现在只返回 library 中不存在的物种数据，所以不需要在外层再判断 `if sci in library`
    ebird_data = {}
    if not zoopicker_only:
        try:
            ebird_data = fetch_ebird_data(library, days, today, warnings)
        except ValueError as error:
            warnings.append(str(error))

    for date_key, species_data in ebird_data.items():
        if date_key not in aggregated:
            aggregated[date_key] = {}
        for sci, data in species_data.items():
            # 这里不需要再过滤 library，因为 fetch_ebird_data 已经过滤过了
            if sci not in aggregated[date_key]:
                aggregated[date_key][sci] = {"total": 0, "locations": {}}

            aggregated[date_key][sci]["total"] += data["total"]
            for key, cnt in data["locations"].items():
                aggregated[date_key][sci]["locations"][key] = aggregated[date_key][sci]["locations"].get(key, 0) + cnt

    # 构建 Markdown 内容
    lines = [f"# 最近{days}天观测到但未收录的鸟种："]
    lines.append(f"\nZoopicker：{completed}/{len(locations)} 个地点完成日期范围抓取。")
    if warnings:
        lines.append("\n> ⚠️ 数据不完整，以下结果仅涵盖成功取得的记录。")
        lines.extend(f"> - {warning}" for warning in warnings)
    if not aggregated:
        lines.append("\n在已取得的数据中未发现新增鸟种；部分数据未完成，不能据此判断没有新增记录。"
                     if warnings else "\n无新增鸟种记录。")
    else:
        for date_key in sorted(aggregated.keys(), reverse=True):
            lines.append(f"\n## {date_key}")
            for sci, data in sorted(aggregated[date_key].items()):
                total = data["total"]
                names = name_map.get(sci, {"chinese": "", "japanese": ""})
                cn = names.get("chinese", "")
                jp = names.get("japanese", "")

                # 如果没有中文名，只显示学名
                title_name = f"{cn}，{jp}，{sci}" if cn else f"{sci} (No CN name)"
                lines.append(f"\n### {title_name} ({total})")

                for key, cnt in sorted(data["locations"].items()):
                    # 统一按 (loc, source, url) 输出；兼容旧数据的 (loc, source)
                    if len(key) == 3:
                        loc, source, source_url = key
                    else:
                        loc, source = key
                        source_url = ""

                    loc_text = f"[{loc}]({source_url})" if source_url else loc
                    lines.append(f"- {loc_text} ({cnt}, {source})")
    return "\n".join(lines)


def write_markdown_to_file(text, date_str):
    export_dir = BASE_DIR / "export"
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
def run_cli(zoopicker_only=False):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["generate", "create-issue"], default="generate",
                        help="运行模式")

    parser.add_argument("--zoopicker-only", action="store_true", default=zoopicker_only,
                        help="只抓取 Zoopicker，不请求 eBird")
    parser.add_argument("--places", type=int, nargs="+", help="只抓取指定地点 ID，例如 767")
    parser.add_argument("--days", type=int, default=num_days, help="最近几天，按日本时区计算")

    args = parser.parse_args()
    if not 1 <= args.days <= 30:
        parser.error("--days 必须在 1 到 30 之间")
    date_str = datetime.datetime.now(JST).strftime("%Y-%m-%d")
    if args.mode == "generate":
        try:
            md = generate_markdown(zoopicker_only=args.zoopicker_only,
                                   place_ids=args.places, days=args.days)
        except ValueError as error:
            parser.error(str(error))
        write_markdown_to_file(md, date_str)
        print(md)
    elif args.mode == "create-issue":
        path = BASE_DIR / "export" / f"{date_str}.md"
        if not os.path.isfile(path):
            print(f"Error: 找不到 Markdown 文件 {path}，请先运行 --mode generate。")
        else:
            with open(path, encoding="utf-8") as f:
                body = f.read()
            create_github_issue(body, date_str)


if __name__ == "__main__":
    run_cli()
