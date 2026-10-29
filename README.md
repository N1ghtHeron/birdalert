# birdalert

_Alert target bird species from Zoopicker and ebird_

## 功能

1. 每天登录抓取[zoopicker](https://zoopicker.com/)和调用[ebird](https://ebird.org/home)接口获取最近的观测记录，按日本时区覆盖日期范围内的分页
2. 对比自己的“生涯列表”，整合并输出【最近几天观测到但未收录的鸟种】
3. 以issue的形式定期更新在github个人仓库中，格式类似：

### 锡嘴雀，シメ，Coccothraustes coccothraustes (75)

- [三鷹市--井の頭公園 (Mitaka--Inokashira Park)](https://ebird.org/checklist/S303878210) (1, ebird)
- [三鷹市--仙川--新川丸池公園 (Mitaka--Sen River--Shinkawamaruike Park)](https://ebird.org/checklist/S303928831) (3, ebird)
- [八王子市--小宮公園 (Hachioji--Komiya Park)](https://ebird.org/checklist/S303875016) (3, ebird)
- [八王子市--長池公園 (Hachioji--Nagaike Park)](https://ebird.org/checklist/S303923108) (1, ebird)
- [坂戸市--浅羽ビオトープ公園 (Sakado--Asaba Biotope Park)](https://ebird.org/checklist/S303903283) (14, ebird)
- [多摩市--東京都立桜ヶ丘公園 (Tama--Tokyo Metropolitan Sakuragaoka Park)](https://ebird.org/checklist/S303896085) (1, ebird)
- [小宮公園(八王子)](https://zoopicker.com/places/574) (1, zoopicker)
- [小金井市--小金井公園 (Koganei--Koganei Park)](https://ebird.org/checklist/S303864638) (50, ebird)
- [長池公園](https://zoopicker.com/places/2513) (1, zoopicker)

## ebird不是已经有鸟讯快报邮件了吗🤔？

因为zoopicker没有鸟讯快报，甚至没有app。~~沟槽的ebird天天给我发三宅岛的鸟👊🐦🔥~~

## 需求

- ebird API
  - 若想只抓取zoopicker的记录则不需要，运行 `python zoopickeronly.py`
- Zoopicker 邮箱登录账号和密码
- 本地调试：
  - python 3.10
  - requirements.txt的包
  - 已包含 python-dotenv，自动从项目根目录的 `.env` 加载本地配置；环境变量优先

## 快速上手

### 1. Fork本仓库

- 点击页面右上角的Fork，修改仓库名称，保存

### 2. 保存自己的配置

- 进入你刚保存的仓库，点击 Setting-Secrets and variables-Actions-Repository secrets
- 点击 New repository secret，添加以下参数并保存（不要上传 `.env`）：
  - Name：ZOOPICKER_EMAIL，Secret：{Zoopicker 登录邮箱}
  - Name：ZOOPICKER_PASSWORD，Secret：{Zoopicker 密码}
  - Name：EBIRD_API_KEY，Secret：{你的ebird API}
  - Name：LAT，Secret：{搜索中心纬度}
  - Name：LNG，Secret：{搜索中心经度}
- 例：如果你希望ebird以东京站为中心搜索观测记录，则LAT为35.68131729933924, LNG为139.76728475585355

### 3. 替换文件，请保证文件名称与格式相同

- 把 data 文件夹下的 ebird_world_life_list.csv 替换成你自己的生涯列表，必须包含【Scientific Name】。在ebird个人页面可以导出，需自行转换成uft-8格式
- （可选）本仓库中的 spot_zoopicker.csv 是东京的zoopicker观鸟热点，你可以上传替换为其他地区的
- （可选）本仓库中的 ebird_taxonomy_integrated.json 是ebird的日本鸟种数据库，你可以参考 tools/get_taxonomy.py 来生成并上传替换其他地区的，必须包含【Scientific Name】

### 4. 测试action

- 回到 Setting 的 General 页面，下拉到 Features，勾选 Issues
- 回到仓库，点击 Actions，选择左侧的 auto alert，点击右侧的 run workflow
- 成功的效果是：auto alert 能成功运行，并提交issue

## ❓可能存在的问题

### Zoopicker 登录、广告和数据完整性

匿名页面仅返回部分记录，程序现在通过网站使用的 Firebase 邮箱密码认证流程建立会话，验证登录后，读取网站内部的观测 JSON 数据并逐页抓取。会话 Cookie 和令牌只保存在内存中，不写入磁盘；登录失效时仅尝试恢复一次。这不是官方公开 API，网站变更时可能需要适配。

每页最多 100 条。程序按观测日期倒序读取，遇到早于日期窗口的记录或读完列表后停止；重复分页、分页上限、数据结构变化等情况会标注不完整。相同鸟种、日期和地点的多条观测会保留，不按这些字段合并去重。

HTTP 429 表示网站限流，并不表示密码错误。GET 请求遵循 `Retry-After`（秒数或 HTTP 日期）；没有该字段时分别等待 30、60 秒，最多重试两次。如果服务器要求等待超过 120 秒，或重试后仍被限流，本轮停止 Zoopicker 请求并在报告中标注未完成，eBird 仍可继续。密码认证 POST 不自动重试。默认 GET 间隔为 2 秒，Actions 已设置同一分支串行运行，避免手动运行与定时运行重叠。若 Actions 持续 429 而本地正常，可能与共享出口 IP 有关，需要等待限制解除或使用自己的 runner；重试不能保证解除服务器限制。

“さらに野鳥の場所情報を見る／短い広告を見る”广告提示与登录分别处理。如果响应要求广告解锁、拒绝访问或缺少地点信息，报告会保留已获取的记录，并明确提示“数据不完整”，不会将其当作没有新鸟。当前程序不会自动观看广告或伪造广告完成状态。仅在浏览器中出现、未体现在服务器响应中的弹窗，无法由 HTTP 客户端检测或操作；如服务器也开始限制观测接口，需要另行接入正常的浏览器解锁流程。


### 为什么输出的只有拉丁名？

是因为ebird和zoopicker**对同一鸟种采用了不同的Scientific Name（拉丁文名称）**。
zoopicker使用的Scientific Name和wikipedia一致，请自行在 `ebird_world_life_list.csv`中标注。
只添加Row #、Common Name、Scientific Name即可，例如：`0,,,金眶鸻,Charadrius dubius,,,,,,,,`

---

## 进阶: 自定义配置

### 调整定期更新issue的时间

修改 `auto_issue.yml`的：

```
schedule:
    - cron: "0 20 * * *"   # UTC 20:00 -> 东9 5:00 github的action有延迟，建议提前1～2小时
    - cron: "0 8 * * *"    # UTC 08:00 -> 东9 17:00
```

### 自定义时间范围、地点范围

修改 `main.py`中，全局配置的 `num_days`（最近n天）、`dist`（搜索半径，km）。

`LAT`（搜索中心纬度）、`LNG`（搜索中心经度）、`EBIRD_API_KEY` 和 Zoopicker 登录配置，请保存在本地 `.env` 或 GitHub Actions Secrets 中。

详见 [ebird API 文档](https://documenter.getpostman.com/view/664302/S1ENwy59)

### 本地调试

1. fork 本仓库并 git clone 至本地
2. 安装依赖。首次配置时，将 `.env.example` 复制为 `.env`；已有 `.env` 时保留原文件。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

3. 在 `.env` 中填写配置，不需要修改 Python 代码。`.env`、虚拟环境及会话目录均已被 Git 忽略。

```dotenv
ZOOPICKER_EMAIL="你的登录邮箱"
ZOOPICKER_PASSWORD="你的密码"
EBIRD_API_KEY="你的eBird API密钥"
LAT="搜索中心纬度"
LNG="搜索中心经度"
```

4. 运行。只抓取 Zoopicker 时可以不填写 eBird 密钥和坐标。

```sh
# 完整报告：配置地点列表中的 Zoopicker 记录，加上 eBird 区域数据
.venv/bin/python main.py --mode generate

# 伊佐沼定点验证：只请求 Zoopicker，最近 3 天
.venv/bin/python main.py --mode generate --zoopicker-only --places 767 --days 3

# 等价的 Zoopicker 专用入口；main.py 和 zoopicker_client.py 需同时保留
.venv/bin/python zoopickeronly.py --places 767

# 离线回归测试，不请求网站、不发布 Issue
.venv/bin/python -m unittest discover -s tests -v
```

本地运行会将 Markdown 保存到项目根目录的 `export/YYYY-MM-DD.md`，日期使用日本时区。指定 `--places` 时仅限制 Zoopicker 地点；eBird 仍按配置的区域查询。相同日期再次生成会覆盖当日报告。只有显式运行 `--mode create-issue` 才会发布 GitHub Issue，本地发布还需配置 `TOKEN` 和 `GITHUB_REPOSITORY`。

### 文件结构

```
├── .github
│   └── workflows
│       └── auto_issue.yml  负责github action自动运行
├── .gitignore
├── LICENSE
├── README.md   （你在这里）
├── data 
│   ├── ebird_taxonomy_integrated.json  ebird的日本鸟种数据库，包含Scientific Name和中、英、日的俗名（comName）
│   ├── ebird_world_life_list.csv       你的生涯列表，需包含【Scientific Name】。下载地址：https://ebird.org/lifelist?r=world ，需自行转换成uft-8格式
│   └── spot_zoopicker.csv              zoopicker东京前5页的观鸟热点（除去三宅岛附近和多摩動物公園）
├── main.py     负责抓网页数据、比对、生成.md、提交issue等所有主要功能
├── zoopicker_client.py  Zoopicker 认证、分页、数据校验及受限状态检测
├── .env.example        不含凭据的配置模板
├── tests/test_zoopicker.py  登录、分页、广告限制及报告回归测试
├── requirements.txt    github action所需环境
└── tools
│   └── get_taxonomy.py 获取不同语言的ebird taxonomy鸟种数据库，并将其合并为ebird_taxonomy_integrated.json。可以使用自己的ebird API改地区和语言
└── zoopickeronly.py    Zoopicker 专用入口，不需要 eBird 配置；与 main.py 共用实现，请勿替换 main.py
```
