# Search Iwara

本项目是一个本地优先的 Oreno3D 元数据镜像站。

它不会下载视频内容，也不尝试本地播放视频；它做的事情是：

- 抓取 `oreno3d.com` 的视频元数据
- 把标题、作者、原作、角色、tag、发布时间、浏览数、点赞数、缩略图和 Iwara 外链写入本地 SQLite
- 提供一个本地 Web UI，解决原站搜索和筛选能力不足的问题

项目内另有一份给另一个 AI 使用的说明文档：


## 当前能力

- 标题 FTS5 检索
- 作者筛选：`包含任一 / 排除`
- 原作筛选：`包含任一 / 排除`
- 角色筛选：`包含任一 / 排除`
- tag 筛选：`全含 / 任一 / 排除`
- 发布时间范围筛选
- 浏览数范围筛选
- 点赞数范围筛选
- 原站风格四种主排序：
  - `急上昇`
  - `高評価`
  - `新着`
  - `人気`
- 本地详情页
- Iwara 外链跳转
- 首页热门聚合：
  - `人気キャラ`
  - `人気作者`
  - `人気カテゴリ`
- 实体榜单页：
  - `/authors`
  - `/characters`
  - `/tags`
  - `/origins`
- 增量同步
- 可断点续跑的全量同步

## 技术栈

- Python 3.13
- `uv`
- SQLite / FTS5
- FastAPI
- Jinja2
- `httpx`
- `selectolax`
- `typer`

## 安装

开发环境：

```bash
uv sync --extra dev
```

仅运行：

```bash
uv sync
```

## 快速开始

### 1. 小范围验证抓取

```bash
uv run search-iwara sync latest --stable-pages 1 --max-pages 1
```

### 2. 启动本地服务

```bash
uv run search-iwara serve
```

默认地址：

```text
http://127.0.0.1:8000
```

### 3. 打开页面

- 首页：`/`
- 详情页：`/movies/{source_site_id}`
- 热门作者页：`/authors`
- 热门角色页：`/characters`
- 热门标签页：`/tags`
- 热门原作页：`/origins`

## 已验证的真实链路

已经实际跑通过：

```bash
uv sync --extra dev
uv run --extra dev pytest
uv run search-iwara sync latest --stable-pages 1 --max-pages 1
uv run search-iwara serve --port 8765
```

已确认：

- 测试通过：`6 passed`
- 真实同步成功：至少抓取并入库了最新页元数据
- 本地页面、详情页、自动补全接口、热门榜和筛选页可访问

## 常用命令

### 增量同步

```bash
uv run search-iwara sync latest
```

说明：

- 从最新页开始抓
- 连续若干页没有新视频或列表变化后停止
- 会补抓失败过的详情页

### 全量同步

```bash
uv run search-iwara sync full
```

说明：

- 从 `/?sort=latest&page=1` 一直扫到最后一页
- 进度写进数据库
- 中断后可继续

### 试运行

```bash
uv run search-iwara sync full --max-pages 3
uv run search-iwara sync latest --max-pages 2
```

### 启动服务

```bash
uv run search-iwara serve
uv run search-iwara serve --port 8765
```

### 测试

```bash
uv run --extra dev pytest
```

## 搜索参数

### 标题

- `q`
- `title_mode=all|any`

### 作者

- `author_any`
- `author_not`

### 原作

- `origin_any`
- `origin_not`

### 角色

- `character_any`
- `character_not`

### Tag

- `tag_all`
- `tag_any`
- `tag_not`

### 时间与热度

- `published_from`
- `published_to`
- `min_views`
- `max_views`
- `min_favorites`
- `max_favorites`

### 排序

- `hot_desc`
- `favorites_desc`
- `published_desc`
- `popularity_desc`
- `published_asc`
- `favorites_asc`
- `views_desc`
- `views_asc`

兼容旧参数：

- `hot` -> `hot_desc`
- `favorites` -> `favorites_desc`
- `latest` -> `published_desc`
- `popularity` -> `popularity_desc`
- `views` -> `views_desc`

### 示例

```text
/?q=Yelan&title_mode=all
/?author_any=4972
/?origin_any=276&character_any=1470
/?tag_any=2,3&tag_not=84
/?published_from=2026-04-01&published_to=2026-04-11&min_views=1000&min_favorites=100
/?sort=hot
/?sort=views_asc
```

## 排序与评分规则

本地站没有原站内部隐藏权重，因此使用可解释的近似评分。

### 主排序

- `高評価`
  - 直接按 `favorite_count` 降序
- `新着`
  - 直接按 `published_at` 降序
- `人気`
  - 综合热度：`view_count + favorite_count * 50`
- `急上昇`
  - 爆发分数：`(view_count + favorite_count * 50) / (距今小时数 + 6)`

### 首页热门榜

- `人気作者`
  - 作者名下作品的综合热度求和
- `人気キャラ`
  - 角色关联作品的综合热度求和
- `人気カテゴリ`
  - 当前实现为 `tag + 原作` 混合榜，按综合热度排序

这些都是基于“当前已抓取到的本地数据”计算，不等于原站的完整全站榜单。

## 自动补全接口

- `/api/authors?query=...`
- `/api/tags?query=...`
- `/api/origins?query=...`
- `/api/characters?query=...`

## 数据库

默认数据库路径：

```text
data/oreno3d.sqlite3
```

自定义数据库路径：

```bash
SEARCH_IWARA_DB=/absolute/path/custom.sqlite3 uv run search-iwara serve
```

或：

```bash
uv run search-iwara sync latest --db-path /absolute/path/custom.sqlite3
```

主要表：

- `movies`
- `authors`
- `tags`
- `origins`
- `characters`
- `movie_tags`
- `movie_origins`
- `movie_characters`
- `crawl_state`
- `crawl_errors`
- `movie_fts`

## 项目结构

```text
search_iwara/
  cli.py
  config.py
  crawler.py
  db.py
  models.py
  parsers.py
  services.py
  web.py
  static/
  templates/
tests/
docs/
```

## 模块说明

### `search_iwara/cli.py`

CLI 入口。提供：

- `sync full`
- `sync latest`
- `serve`

### `search_iwara/services.py`

同步编排层。

- `sync_full()` 负责全量与断点续跑
- `sync_latest()` 负责最新页增量抓取

### `search_iwara/crawler.py`

远端抓取层。

- 异步请求 Oreno3D
- 限流
- 重试
- 404 特殊处理

### `search_iwara/parsers.py`

HTML 解析层。

- `parse_listing_page()` 解析列表页
- `parse_movie_detail()` 解析详情页

注意：这里有图标文本清洗逻辑，防止把 `face`、`local_offer` 之类的图标字样混进实体名。

### `search_iwara/db.py`

数据库层与查询层。

- schema 初始化
- 实体 upsert
- 搜索条件拼装
- 排序
- 热门榜聚合

### `search_iwara/web.py`

FastAPI 路由层。

- 搜索页
- 详情页
- 自动补全接口
- 实体榜单页

## 当前的重要约束

- 只抓元数据，不抓视频文件
- 缩略图默认直接引用原站 URL，不做本地缓存
- 本地站不内嵌播放器，只负责搜索、展示、跳转
- 热门榜只基于本地已抓到的数据，不代表原站完整榜单

## 开发建议

如果你改了以下任一部分，至少重跑：

- 解析器
- 数据库搜索逻辑
- 路由
- 模板

建议命令：

```bash
uv run --extra dev pytest
uv run search-iwara sync latest --stable-pages 1 --max-pages 1
```

如果要手动查看数据库：

```bash
sqlite3 data/oreno3d.sqlite3
```

## 常见排查

### 搜索命中了，但页面没有显示

先直接查数据库：

```bash
uv run python - <<'PY'
from search_iwara.db import Repository
from search_iwara.models import SearchFilters
repo = Repository.open("data/oreno3d.sqlite3")
print(repo.search_movies(SearchFilters(q="Yelan"), page=1, page_size=20)["total"])
repo.close()
PY
```

### 原作 / 角色名称带有 `face` / `local_library`

说明数据可能是旧版本解析结果。重新抓一次详情页即可清洗。

### 首页热门榜很少

说明当前本地库还小。继续跑 `sync latest` 或 `sync full`。
