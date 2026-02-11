# birdalert
_Alert target bird species from Zoopicker and ebird_

## 功能
1. 每天自动抓取[zoopicker](https://zoopicker.com/)和[ebird](https://ebird.org/home)上最近的观测记录
2. 对比自己的“生涯列表”，整合并输出【最近几天观测到但未收录的鸟种】
3. 以issue的形式定期更新在github个人仓库中，格式：
```
## 2026-02-09 (星期一)
### 红胁蓝尾鸲，ルリビタキ，Tarsiger cyanurus (5)
- 小宮公園(八王子) (1, zoopicker)
- 東京都多摩地域 (1, zoopicker)
- 東大和市--狭山公園 (Higashiyamato--Sayama Park) (1, ebird)
- 横浜市--横浜市こども自然公園 (Yokohama--Yokohama Children's Nature Park) (1, ebird)
- 水元公園 (1, zoopicker)
```

## ebird不是已经有鸟讯快报邮件了吗🤔？
因为zoopicker没有鸟讯快报，甚至没有app。~~沟槽的ebird天天给我发三宅岛的鸟👊🐦🔥~~

## 需求
- ebird API
  - 若想只抓取zoopicker的记录则不需要，详见`zoopickeronly.py`
- 本地调试：
  - python 3.10
  - requirements.txt的包
  - python-dotenv，用于加载ebird API等隐私数据

## 快速上手
### 1. Fork本仓库
  - 点击页面右上角的Fork，修改仓库名称，保存
### 2. 保存自己的配置
  - 进入你刚保存的仓库，点击 Setting-Secrets and variables-Actions-Repository secrets
  - 点击 New repo`sitory secrets, 分别添加以下3个参数并保存：
    - Name：EBIRD_API_KEY，Secret：{你的ebird API}
    - Name：LAT，Secret：{搜索中心经度}
    - Name：LNG，Secret：{搜索中心纬度}
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
### 为什么输出的只有拉丁名？
是因为ebird和zoopicker**对同一鸟种采用了不同的Scientific Name（拉丁文名称）**。
zoopicker使用的Scientific Name和wikipedia一致，请自行在`ebird_world_life_list.csv`中标注。
只添加Row #、Common Name、Scientific Name即可，例如：`0,,,金眶鸻,Charadrius dubius,,,,,,,,`

---

# 进阶
## 自定义配置
### 调整定期更新issue的时间
修改`auto_issue.yml`的： 
```
schedule:
    - cron: "0 20 * * *"   # UTC 20:00 -> 东9 5:00 github的action有延迟，建议提前1～2小时
    - cron: "0 8 * * *"    # UTC 08:00 -> 东9 17:00
```
### 自定义时间范围、地点范围
修改`main.py`中，全局配置的`num_days`（最近n天）、`dist`（搜索半径，km）。

`lat`（搜索中心经度）、`lng`（搜索中心纬度）、和`EBIRD_API_KEY`是**隐私数据**，请自行保存在 Setting-Secrets and variables-Actions-Repository secrets 当中。

详见 [ebird API 文档](https://documenter.getpostman.com/view/664302/S1ENwy59)

### 本地调试
1. fork 本仓库并 git clone 至本地
2. 在本地创建.env文件，格式如下（不要带空格！）
```
EBIRD_API_KEY=你的ebirdAPI
LAT=指定坐标经度，根据不同的url配置可以不用
LNG=指定坐标纬度，根据不同的url配置可以不用
```
3. 本地调试需要的代码已经使用TODO标出，解除注释即可
4. 在路径下的终端执行
```
python main.py --mode generate
```
本地调试会在输出结果的同时，将markdown文件保存到仓库根目录下的export文件夹中


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
├── requirements.txt    github action所需环境
└── tools
│   └── get_taxonomy.py 获取不同语言的ebird taxonomy鸟种数据库，并将其合并为ebird_taxonomy_integrated.json。可以使用自己的ebird API改地区和语言
└── zoopickeronly.py    此代码【只抓取zoopicker的记录】，不需要ebird API。可以删除原有的main.py后将其更名为main.py来实现相同的功能
```
