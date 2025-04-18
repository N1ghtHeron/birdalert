# coding: utf-8
import requests
from bs4 import BeautifulSoup
import datetime
import csv
from datetime import timedelta

num_days = 3

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
    生成最近 num_days 天的目标日期映射：
      key: 页面中记录的日语格式，例如 "2025年4月14日(月)に観察"
      value: 输出中显示的中文格式，例如 "2025-04-14 (星期一)"
    """
    # Python中weekday()：0表示星期一
    jp_week_map = {0: "月", 1: "火", 2: "水", 3: "木", 4: "金", 5: "土", 6: "日"}
    cn_week_map = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日"}

    mapping = {}
    today = datetime.datetime.now()
    for i in range(num_days):
        d = today - timedelta(days=i)
        # 页面日语格式示例："2025年4月14日(月)に観察"
        target_jp = f"{d.year}年{d.month}月{d.day}日({jp_week_map[d.weekday()]})に観察"
        # 输出格式，如 "2025-04-14 (星期一)"
        output_date = f"{d.strftime('%Y-%m-%d')} ({cn_week_map[d.weekday()]})"
        mapping[target_jp] = output_date
    return mapping

def parse_records_jp(html, target_date_mapping):
    """
    解析日语页面中的鸟种记录，假设每条记录占三行：
      第1行：鸟种日文名称（例如：ホウロクシギ）
      第2行：包含英文名称及拉丁文，例如 "Far Eastern Curlew / Numenius madagascariensis"
      第3行：记录日期，例如 "2025年4月14日(月)に観察"
    如果第3行内容出现在 target_date_mapping 中，则提取该记录信息，
    返回字典：键为页面日期（例如 "2025年4月14日(月)に観察"），
    值为记录列表，每个记录为 {"observed_jp": <页面鸟种日文>, "scientific": <拉丁文>}
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    # 去除空行
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    records_by_date = {}
    for i, line in enumerate(lines):
        if line in target_date_mapping:
            if i >= 2:
                observed_jp = lines[i-2]
                mid_line = lines[i-1]
                parts = mid_line.split("/")
                scientific = parts[1].strip() if len(parts) > 1 else ""
                rec = {"observed_jp": observed_jp, "scientific": scientific}
                records_by_date.setdefault(line, []).append(rec)
    return records_by_date

def load_library(csv_file):
    """
    从已收录鸟种库 CSV 文件中加载数据，
    CSV 文件中要求至少包含字段 "Scientific Name"（拉丁文名称）。
    返回一个 set，包含所有已收录的科学名称。
    """
    library = set()
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sci = row.get("Scientific Name", "").strip()
            if sci:
                library.add(sci)
    return library

def load_mapping(csv_file):
    """
    从鸟种名称映射 CSV 文件中加载数据，
    该 CSV 文件格式：英文名, 拉丁文名, 中文名, 其他信息
    中间可能存在空行，应忽略。
    返回一个字典，键为拉丁文名称，
    值为 {"chinese": <中文名>, "japanese": <日文名>}。
    该示例中映射 CSV 文件中没有日文名称，因此 'japanese' 字段为空，
    后续输出时若为空则使用页面记录中的日文名称。
    """
    mapping = {}
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue
            # 如果存在标题行，则跳过（例如第一列为 "English Name"）
            if row[0].strip() == "English Name":
                continue
            if len(row) < 3:
                continue
            latin = row[1].strip()
            chinese = row[2].strip()
            mapping[latin] = {"chinese": chinese, "japanese": ""}
    return mapping

def load_locations(csv_file):
    """
    从 CSV 文件中加载观鸟地列表，
    CSV 文件格式：id,地点名称
    返回一个列表，每个元素为字典，形如：
      { "url": "https://zoopicker.com/places/<id>/watcheds", "location": <地点名称> }
    """
    locations = []
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue
            # 如果有标题行，以数字为 id的行即可
            try:
                place_id = row[0].strip()
                # 若 id 不能转换为数字，则可能是标题行，忽略
                int(place_id)
            except ValueError:
                continue
            loc_name = row[1].strip() if len(row) >= 2 else ""
            url = f"https://zoopicker.com/places/{place_id}/watcheds"
            locations.append({"url": url, "location": loc_name})
    return locations

def main():
    # 从 CSV 文件加载观鸟地点列表
    locations_csv = "data/spot_zoopicker.csv"  # 请提供正确路径
    try:
        location_list = load_locations(locations_csv)
    except Exception as e:
        print("读取观鸟地点 CSV 文件失败：", e)
        return

    # 生成最近 num_days 天的目标日期映射
    target_date_mapping = get_target_date_mapping(num_days=num_days)

    # 加载已收录鸟种库 CSV（用于比对），要求含有字段 "Scientific Name"
    library_csv = "data/ebird_world_life_list.csv"  # 请提供正确路径
    try:
        library_set = load_library(library_csv)
    except Exception as e:
        print("读取已收录鸟种库 CSV 文件失败：", e)
        return

    # 加载鸟种名称映射 CSV（用于输出中文名称），格式：英文名, 拉丁文名, 中文名, 其他信息
    mapping_csv = "data/Avibase_Tokyo.csv"  # 请提供正确路径
    try:
        name_mapping = load_mapping(mapping_csv)
    except Exception as e:
        print("读取鸟种名称映射 CSV 文件失败：", e)
        return

    # 按日期和地点收集解析记录
    # results[output_date][location] = list of records, 每个记录为 {"observed_jp": ..., "scientific": ...}
    results = {}
    for loc in location_list:
        url = loc["url"]
        loc_name = loc["location"]
        try:
            html = fetch_page(url)
        except Exception as e:
            print(f"获取 {loc_name} 页面失败：", e)
            continue
        rec_by_date = parse_records_jp(html, target_date_mapping)
        for page_date, rec_list in rec_by_date.items():
            output_date = target_date_mapping.get(page_date, page_date)
            # 筛选出未收录记录（依据拉丁文比对）
            missing = [r for r in rec_list if r["scientific"] and r["scientific"] not in library_set]
            if missing:
                results.setdefault(output_date, {}).setdefault(loc_name, []).extend(missing)

    # 合并统计相同日期下相同物种的数据
    # aggregated[output_date][scientific] = {
    #   "total": count,
    #   "observed_jp": 页面记录中备用的日文名称,
    #   "locations": { location: count, ... }
    # }
    aggregated = {}
    for date_key, loc_dict in results.items():
        aggregated.setdefault(date_key, {})
        for loc_name, records in loc_dict.items():
            for rec in records:
                sci = rec["scientific"]
                sp_data = aggregated[date_key].get(sci, {"total": 0, "observed_jp": rec["observed_jp"], "locations": {}})
                sp_data["total"] += 1
                sp_data["locations"][loc_name] = sp_data["locations"].get(loc_name, 0) + 1
                aggregated[date_key][sci] = sp_data

    # 生成 Markdown 格式输出
    md_lines = []
    md_lines.append(f"# 最近{num_days}天中观测到但未收录的鸟种：")
    if not aggregated:
        md_lines.append("无新增鸟种记录。")
    else:
        for date_key in sorted(aggregated.keys(), reverse=True):
            md_lines.append(f"\n## {date_key}")
            species_dict = aggregated[date_key]
            for sci in sorted(species_dict.keys()):
                sp = species_dict[sci]
                total_count = sp["total"]
                mapping_entry = name_mapping.get(sci, {})
                cn_name = mapping_entry.get("chinese", "")
                # 若映射中未提供日文，则使用页面记录中的日文作为备用
                jp_name = mapping_entry.get("japanese", "") if mapping_entry.get("japanese", "") else sp["observed_jp"]
                md_lines.append(f"\n### {cn_name}，{jp_name}，{sci} ({total_count})")
                for loc_name in sorted(sp["locations"].keys()):
                    loc_count = sp["locations"][loc_name]
                    md_lines.append(f"- {loc_name} ({loc_count})")

    markdown_text = "\n".join(md_lines)
    print(markdown_text)

if __name__ == "__main__":
    main()

