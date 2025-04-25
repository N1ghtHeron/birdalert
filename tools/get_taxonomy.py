# get_taxonomy.py
# LOCAL
"""
1. 用 http.client 从 eBird API 获取三种语言的 taxonomy 数据；
2. 将三个语言版本分别保存为 JSON 文件；
3. 然后加载这些文件，合并中文、日文译名到英文版本中；
4. 最后保存整合后的数据到一个新文件。
"""

import os
import http.client
import json
from dotenv import load_dotenv

# 载入 .env 文件中的 API Token
load_dotenv()
EBIRD_API_TOKEN = os.getenv("EBIRD_API_KEY")

if not EBIRD_API_TOKEN:
    raise ValueError("EBIRD_API_KEY not found in .env file")

# 获取 taxonomy 数据的函数
def fetch_taxonomy(locale, output_file):
    conn = http.client.HTTPSConnection("api.ebird.org")
    headers = {
        "X-eBirdApiToken": EBIRD_API_TOKEN
    }
    endpoint = f"/v2/ref/taxonomy/ebird?fmt=json&locale={locale}"
    conn.request("GET", endpoint, '', headers)
    res = conn.getresponse()
    data = res.read().decode("utf-8")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(data)
    print(f"{locale} 版本的 taxonomy 已保存至 {output_file}")

# 下载三种语言的 taxonomy 数据
os.makedirs("../data", exist_ok=True)
fetch_taxonomy("en", "../data/ebird_taxonomy_en.json")
fetch_taxonomy("zh_SIM", "../data/ebird_taxonomy_zh_SIM.json")
fetch_taxonomy("ja", "../data/ebird_taxonomy_ja.json")

# 加载 JSON 文件
def load_taxonomy(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

# 加载数据
taxonomy_en = load_taxonomy("../data/ebird_taxonomy_en.json")
taxonomy_zh = load_taxonomy("../data/ebird_taxonomy_zh_SIM.json")
taxonomy_ja = load_taxonomy("../data/ebird_taxonomy_ja.json")

# 构建语言映射表
mapping_zh = {item["speciesCode"]: item["comName"] for item in taxonomy_zh if "speciesCode" in item and "comName" in item}
mapping_ja = {item["speciesCode"]: item["comName"] for item in taxonomy_ja if "speciesCode" in item and "comName" in item}

# 整合中文和日文名称
for record in taxonomy_en:
    code = record.get("speciesCode")
    record["comName_zh_SIM"] = mapping_zh.get(code, "未知")
    record["comName_ja"] = mapping_ja.get(code, "未知")

# 保存整合后的文件
output_file = "../data/ebird_taxonomy_integrated.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(taxonomy_en, f, ensure_ascii=False, indent=2)

print(f"整合后的 taxonomy 已保存至 {output_file}")
