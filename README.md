# birdalert

_Alert target bird species from Zoopicker and ebird_

## 功能
1. 每天自动抓取整合[zoopicker](https://zoopicker.com/)和[ebird](https://ebird.org/home)上最近的观测记录
2. 对比自己的“生涯列表”，输出【最近几天观测到但未收录的鸟种】
3. 以issue的形式定期更新在github个人仓库中

## ebird不是已经有鸟讯快报邮件了吗🤔？
然而zoopicker不光没有鸟讯快报邮件，甚至没有app

~~沟槽的ebird天天给我发三宅岛父岛的鸟，我踏马还能不知道在海上能看信天翁吗，没去加新还不是因为没有钱👊🐦🔥~~

## 需求
- ebird API
  - 若想只抓取zoopicker的记录则不需要，详见`zoopickeronly.py`
- 如需本地调试：
  - python 3.10
  - requirements.txt的包
  - python-dotenv，用于加载ebird API等隐私数据

## 快速上手
### 1. Fork本仓库
  - 点击页面右上角的Fork，修改仓库名称，保存
### 2. 保存自己的配置
  - 进入你刚保存的仓库，点击 Setting-Secrets and variables-Actions-Repository secrets
  - 点击 New repository secrets, 分别添加以下3个参数并保存：
    - Name：EBIRD_API_KEY，Secret：{你的ebird API}
    - Name：lat，Secret：{你希望指定搜索的区域中心经度}
    - Name：lng，Secret：{你希望指定搜索
### 3. 测试action
  - 回到 Setting 的 General 页面，下拉到 Features，勾选 Issues
  - 回到仓库，点击 Actions，同意workflow，点击 run workflow
  - 如果你的 auto alert 能成功运行并提交issue，则大功告成！

---
# 进阶

## 文件结构
```
├── .github
│   └── workflows
│       └── auto_issue.yml  负责github action自动运行
├── .gitignore
├── LICENSE
├── README.md   你正在阅读的本文
├── data        数据库
│   ├── ebird_taxonomy_integrated.json  ebird的日本鸟种数据库，包含中文、英语、日语的常用名
│   ├── ebird_world_life_list.csv       你的生涯列表，需包含【Scientific Name】。在ebird个人页面可以导出，需自行转换成uft-8格式
│   └── spot_zoopicker.csv              zoopicker前5页的观鸟热点，共129处（除去三宅岛附近和多摩動物公園）
├── main.py     负责抓网页数据、比对、生成markdown文件、提交issue等所有主要功能
├── requirements.txt    github action所需环境
└── tools
│   └── get_taxonomy.py 用于获取不同语言的ebird taxonomy鸟种数据库，并将其合并。可以使用自己的ebird API改地区和语言
└── zoopickeronly.py    【只抓取zoopicker的记录】，因此不需要ebird API，可以删除原有的main.py后将其更名为main.py来实现相同的功能
```



## 更多自定义配置
### 调整定期更新issue的时间
修改`auto_issue.yml`中下面的部分： 
```
schedule:
    - cron: "0 20 * * *"   # UTC 20:00 -> 东9 5:00 github的action有延迟
    - cron: "0 2 * * *"    # UTC 02:00 -> 东9 11:00
    - cron: "0 13 * * *"   # UTC 13:00 -> 东9 22:00
```
### 调整抓取"最近几天"的时间范围
修改`main.py`中，全局配置的`num_days`
### 调整ebird抓取的鸟种记录的地理范围
修改`main.py`中，全局配置的`url`

本代码的`url`的意义是查询指定经纬度坐标`(lat, lng)`半径`dist`千米范围内，所有观鸟热点的鸟种记录。

`lat`, `lng`和`EBIRD_API_KEY`是隐私数据，需要自行保存在 Setting-Secrets and variables-Actions-Repository secrets 当中。

ebird API也提供了其他查询鸟种记录的方式，比如直接指定某一地区。详见 [ebird API 文档](https://documenter.getpostman.com/view/664302/S1ENwy59)
```
# ----------------------- 全局配置 ----------------------------
num_days = 3    # 最近几天数据
ebird_token = os.getenv("EBIRD_API_KEY")    # eBird API Token
lat = float(os.getenv("LAT"))   # center location
lng = float(os.getenv("LNG"))
dist = 40   # radius distance (km)
lang = "zh_SIM"
url = f"/v2/data/obs/geo/recent?lat={lat}&lng={lng}&back={num_days}&dist={dist}&hotspot=true&sppLocale={lang}"
```
### 本地调试
1. fork 本仓库并 git clone 至本地
2. 在本地创建.env文件，格式如下（不要带空格！）
```
EBIRD_API_KEY=你的ebirdAPI
lat=指定坐标经度，根据不同的url配置可以不用
lng=指定坐标纬度，根据不同的url配置可以不用
```
3. 本地调试需要的代码已经使用TODO标出，解除注释即可，如下所示
```
# TODO：----------------------- local debug ----------------------------
# from dotenv import load_dotenv
# load_dotenv()
```
以及
```
    parser.add_argument("--mode", choices=["generate", "create-issue"], required=True,
                        help="运行模式: generate(生成 Markdown), create-issue(根据 Markdown 创建 GitHub Issue)")
    # TODO：----------------------- local debug 则改成 ----------------------------
    # parser.add_argument("--mode", choices=["generate", "create-issue"],
    #                     default="generate",  # 设置默认模式
    #                     help="运行模式: generate(生成 Markdown), create-issue(根据 Markdown 创建 GitHub Issue)")
```
4. 本地调试会在输出结果的同时，将markdown文件保存到仓库根目录下的export文件夹中