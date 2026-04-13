# Search Iwara

[English](./README.md) · 简体中文

**在线示例（NSFW）：** <https://zundamon.dpdns.org/>

**社区友链：** [LINUX DO](https://linux.do/)

![License: MIT](https://img.shields.io/badge/License-MIT-f2c94c?style=flat-square)
![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white)
![Backend FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![Database SQLite + FTS5](https://img.shields.io/badge/Database-SQLite%20%2B%20FTS5-003B57?style=flat-square&logo=sqlite&logoColor=white)

[Oreno3D](https://oreno3d.com/) 元数据的本地镜像，提供原站不具备的高级搜索与筛选能力。

**提示：** 在线示例会展示成人向内容元数据，请勿在办公或公共场合直接打开。

本项目从 Oreno3D 抓取视频元数据（标题、作者、标签、原作、角色、观看/收藏数、缩略图、Iwara 链接），存入本地 SQLite，并通过 Web UI 提供搜索、筛选与浏览。

**本项目不下载、不托管任何视频文件，仅对元数据建立索引与搜索。**

## 功能

- **标题全文搜索**（SQLite FTS5）
- **实体布尔筛选** — 按作者、原作、角色、标签进行包含/排除（any / all / not）
- **区间筛选** — 发布日期、观看数、收藏数
- **四种排序** 与原站对齐：急上昇 / 高評価 / 新着 / 人気
- **相关视频** — 详情页根据同作者 / 共同角色 / 共同原作 / 共同标签加权推荐
- **三态主题** — 浅色 / 深色 / 跟随系统，默认跟随系统
- **热门榜单** — 侧栏聚合热门角色、作者、分类
- **实体浏览** — `/characters` `/authors` `/tags` `/origins` 带排名，作者页含作品轮播
- **增量 & 全量同步** — 可断点续抓，失败自动重试
- **终端进度条** — 页面进度 + 详情抓取进度
- **并发可调** — 请求并发、预取窗口、详情批量大小均可配置
- **响应式布局** — 移动端侧栏抽屉，自适应网格

## 技术栈

- Python 3.13、[uv](https://github.com/astral-sh/uv)
- SQLite / FTS5
- FastAPI + Jinja2
- httpx + selectolax
- 原生 CSS（CSS 变量）+ 原生 JS

## 快速开始

### 安装

```bash
uv sync
```

### 抓取数据

```bash
# 快速测试：只抓最新一页
uv run search-iwara sync latest --stable-pages 1 --max-pages 1

# 增量同步：拉取上次运行之后的新视频
uv run search-iwara sync latest

# 全量同步：抓取全部（可断点续传）
uv run search-iwara sync full

# 更快的全量同步（根据你的网络和目标站点承受能力调整）
uv run search-iwara sync full \
  --request-concurrency 24 \
  --request-delay-ms 0 \
  --list-prefetch-pages 16 \
  --detail-batch-size 192
```

### 启动 Web UI

```bash
uv run search-iwara serve
# 或指定端口
uv run search-iwara serve --port 8765
```

在浏览器中打开 `http://127.0.0.1:8000`（默认）。

## Linux 部署

仓库自带 Linux 部署模板：

- `systemd` Web 服务
- `systemd` 定时器（执行 `sync latest`）
- `nginx` 反向代理到你自己的域名

文件位于 [`deploy/linux`](./deploy/linux)，完整说明参见 [docs/linux-deploy.md](./docs/linux-deploy.md)。

不想手动改配置的话，可以用交互式管理脚本：

```bash
sudo ./deploy/linux/manage.py
```

该脚本能识别安装状态、引导首次安装、修改同步默认参数、手动执行同步、管理 nginx 模式 / 域名 / TLS 路径。

典型服务器安装：

```bash
sudo ./deploy/linux/install.sh \
  --sync-hours 6
```

它会安装：

- `search-iwara-web.service`
- `search-iwara-sync.service`
- `search-iwara-sync.timer`
- 自动安装缺失的 `uv`
- 一份通用的 nginx 站点配置（你自行替换域名）

启用 nginx 模式时，安装脚本会在系统缺失 nginx 时自动安装。

如果你只想让应用直接监听公网端口、不走 nginx：

```bash
sudo ./deploy/linux/install.sh \
  --skip-nginx \
  --web-host 0.0.0.0 \
  --web-port 8000
```

## 页面

| 路由 | 说明 |
|------|------|
| `/` | 搜索与浏览，包含筛选面板与排序 tab |
| `/movies/{id}` | 视频详情页，含元数据网格与相关视频 |
| `/characters` | 角色排行，可直达搜索 |
| `/authors` | 作者排行，附作品轮播 |
| `/tags` | 标签排行 |
| `/origins` | 原作 / IP 排行 |

## 抓取速度调优

抓取瓶颈主要在网络。默认参数：

- `request_concurrency = 12`
- `request_delay_seconds = 0.05`
- `listing_prefetch_pages = 8`
- `detail_batch_size = 96`

可在命令行覆盖：

```bash
uv run search-iwara sync full \
  --request-concurrency 24 \
  --request-delay-ms 0 \
  --list-prefetch-pages 16 \
  --detail-batch-size 192
```

建议：

- 先用 `--request-concurrency 24 --request-delay-ms 0`
- 如果目标站开始失败或变慢，把并发降到 `16`
- 请求并发稳定之后，再逐步增大 `--list-prefetch-pages` 和 `--detail-batch-size`

## 抓取进度输出

两个 sync 命令都会显示终端进度条：

- **页面进度**
  - `sync full`：当前页 / 总页数
  - `sync latest`：当前页及 stable-page 停止状态
- **详情进度**
  - 当前批次内已抓取的详情页数量

示例：

```text
full page 53/8823
pages 49-56 details
```

## 搜索参数

所有参数都是 `/` 路径上的可选查询字符串。

| 类别 | 参数 |
|------|------|
| 标题 | `q`、`title_mode=all\|any` |
| 作者 | `author_any`、`author_not` |
| 原作 | `origin_any`、`origin_not` |
| 角色 | `character_any`、`character_not` |
| 标签 | `tag_all`、`tag_any`、`tag_not` |
| 日期区间 | `published_from`、`published_to` |
| 观看区间 | `min_views`、`max_views` |
| 收藏区间 | `min_favorites`、`max_favorites` |
| 排序 | `sort=hot\|favorites\|latest\|popularity\|views_desc\|...` |

### 示例

```
/?q=Yelan&title_mode=all
/?author_any=4972&sort=hot
/?origin_any=276&character_any=1470
/?tag_any=2,3&tag_not=84
/?min_views=1000&min_favorites=100&sort=popularity
```

## 评分与排行

所有排行均基于**本地已抓取的数据**计算，并不等同于原站的真实全站排行。

| 模式 | 公式 |
|------|------|
| 高評価 | `favorite_count DESC` |
| 新着 | `published_at DESC` |
| 人気 | `view_count + favorite_count * 50` |
| 急上昇 | `(view_count + favorite_count * 50) / (hours_since_publish + 6)` |

### 相关视频算法

详情页最多展示 12 个相关视频，评分规则：

| 维度 | 权重 |
|------|------|
| 同作者 | +10 |
| 每个共同角色 | +5 |
| 每个共同原作 | +5 |
| 每个共同标签 | +1 |

同分时按热度分（人気）再排序。

## 数据库

默认路径：`data/oreno3d.sqlite3`

通过环境变量覆盖：

```bash
SEARCH_IWARA_DB=/path/to/custom.sqlite3 uv run search-iwara serve
```

## 开发

```bash
# 安装开发依赖
uv sync --extra dev

# 运行测试
uv run --extra dev pytest

# 快速抓取 + 启动，用于手动验证
uv run search-iwara sync latest --stable-pages 1 --max-pages 1
uv run search-iwara serve --port 8765
```

### 项目结构

```
search_iwara/
  cli.py          # Typer CLI：sync full / sync latest / serve
  services.py     # 同步编排、预取、详情批处理、进度事件
  crawler.py      # 面向 oreno3d.com 的异步 HTTP（限流、重试）
  parsers.py      # 通过 selectolax 把 HTML 变成结构化字段
  db.py           # SQLite schema、upsert、FTS5 搜索、排行
  models.py       # dataclass 模型
  config.py       # 设置项（DB 路径、并发、延迟、批量大小）
  web.py          # FastAPI 路由
  utils.py        # URL 解析、格式化、分页辅助
  static/
    style.css     # 基于 CSS 变量的浅/深色主题
    app.js        # 主题切换、筛选面板、自动补全 chip
  templates/
    base.html     # 布局：header、sidebar、主题切换
    index.html    # 搜索页：排序 tab 与可折叠筛选
    movie_detail.html  # 详情页：相关视频
    entity_index.html  # 实体排行页
tests/
  test_parsers.py
  test_repository.py
  test_web.py
```

## License

本项目使用 MIT 协议，详见 [LICENSE](./LICENSE)。
