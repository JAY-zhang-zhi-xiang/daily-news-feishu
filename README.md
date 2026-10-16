# 每日新闻飞书机器人

[![CI](https://github.com/JAY-zhang-zhi-xiang/daily-news-feishu/actions/workflows/ci.yml/badge.svg)](https://github.com/JAY-zhang-zhi-xiang/daily-news-feishu/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

抓取 RSS 新闻，用 DeepSeek 做「新闻价值评分」和中文解读，每天早上把约 20 条真正值得看的内容推送到飞书。

## 它想解决什么问题

市面上的 AI 新闻聚合工具大多面向「AI / 技术行业资讯」，按主题或来源组织内容。这个项目不一样，它只服务一个场景：

> **一个中文读者，想在早上花几分钟，同时知道国内和国外发生了什么，且不被单一来源淹没。**

所以下面几件事是这个项目的**核心设计**，而不是附带功能：

- **国内 / 国外显式配比**：筛选链路的每一步都按「两边各约占三分之一」来平衡，而不是交给默认排序。
  国内源覆盖人民网、新华社、央视、澎湃、财新、第一财经、观察者网、环球网等。
- **不是只靠关键词**：`规则粗筛 → DeepSeek 语义评分 → 多样性控制` 三级筛选。
- **中文白话解读**：标题改写成不像通稿的人话；摘要先说「发生了什么」，再翻译「这跟我有什么关系」。
- **区分事实与说法**：只属于某一来源的说法会写成「某方称」，不直接当既成事实。
- **对官话、套话、商业话术可以轻微调侃**，但涉及伤亡灾难时保持克制。
- **失败不静默**：AI 环节挂了，卡片会明确标出「本期为降级输出」，不会假装一切正常。

## 为什么用它而不是别的

| 维度 | 本项目 | 典型同类项目 |
|---|---|---|
| 定位 | 中文读者，国内外均衡 | 多为 AI/技术行业资讯 |
| 依赖 | 3 个 pip 包，单脚本 | 常见 Docker / 嵌入模型 |
| 部署 | 一台小服务器 + cron | 常见容器编排 |
| 去重 | 标题相似度 + 跨天去重 | 部分使用向量语义去重 |
| 推送 | 飞书卡片 | 常见网页 / 邮件 / 多平台 |

取舍很明确：**功能边界更窄，但部署更省、无人值守更稳**。如果你需要多源抓取（Hacker News / Reddit / X / Telegram）、向量语义去重或网页看板，这个项目不适合你，去看看 Horizon 之类的项目。

## 快速开始

```powershell
.\setup.ps1                     # 创建虚拟环境并安装依赖
.\.venv\Scripts\python.exe .\src\main.py --check-config       # 只检查配置
.\.venv\Scripts\python.exe .\src\main.py --dry-run            # 完整生成但不发送
.\run_daily_news.ps1            # 真正发送一次
```

也可以用 pip 安装（提供 `daily-news` 命令）：

```bash
pip install .
daily-news --check-config
```

Linux 服务器与定时任务配置见下方[服务器部署](#服务器部署)。

## 可靠性与日志

无人值守运行时，最怕的是"悄悄失效"。这个项目为此做了几件事：

- **飞书发送带重试**（3 次，指数退避）。它是唯一的交付出口，一次网络抖动就意味着当天没有日报。
- **DeepSeek 调用带重试**（2 次）。429 限流或瞬时超时不再直接降级。
- **确定性错误不重试**。401/403 鉴权失败、400 参数错误会立刻返回，不做无谓等待。
- **AI 降级可见**。任何 AI 环节失败，卡片顶部会出现橙色告警并写明原因（见上文）。
- **结构化日志**。诊断信息带级别与时间戳输出到 stderr，与 CLI 结果（stdout）分离，cron 里可以直接按级别过滤：

```bash
# 只看警告及以上
python src/main.py 2>&1 | grep WARNING

# 打开调试级别
python src/main.py --verbose
```

## 文件说明

- `src/main.py`：主程序
- `.env.example`：环境变量模板
- `requirements.txt`：Python 依赖
- `requirements.lock.txt`：已验证依赖锁定版本，生产部署优先使用
- `check_release.ps1`：上线前检查脚本
- `setup.ps1`：Windows 本地创建虚拟环境并安装依赖
- `run_daily_news.ps1`：Windows 本地手动运行一次
- `register_task.ps1`：Windows 本地注册定时任务
- `pyproject.toml`：打包配置（支持 `pip install .`）
- `.github/workflows/ci.yml`：CI，push/PR 时自动跑测试与密钥扫描
- `LICENSE`：MIT 协议

## 配置说明

复制 `.env.example` 为 `.env`，然后填写：

```env
DEEPSEEK_API_KEY=你的 DeepSeek Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_THINKING_MODE=disabled

FEISHU_WEBHOOK_URL=你的飞书机器人 Webhook
FEISHU_BOT_SECRET=

NEWS_HOURS=24
MAX_ARTICLES=80
VALUE_SCORE_CANDIDATES=60
MAX_SUMMARY_ITEMS=20

# 可选：服务器直连国外 RSS 不稳定时使用
RSS_PROXY=http://127.0.0.1:7890

# RSS 或 OPML 地址，用英文逗号分隔
RSS_FEEDS=https://example.com/rss.xml,https://example.com/feed.xml
```

说明：

- `MAX_ARTICLES=80`：先抓 80 条候选新闻。
- `DEEPSEEK_THINKING_MODE=disabled`：日报生成默认关闭 thinking mode，让输出更快、更稳定；需要更强推理时可改为 `enabled`。
- `VALUE_SCORE_CANDIDATES=60`：最多拿 60 条给 DeepSeek 做新闻价值评分。
- `MAX_SUMMARY_ITEMS=20`：最终发送约 20 条。
- `RSS_PROXY`：只影响 RSS 抓取，不影响 DeepSeek 和飞书请求。
- `NEWS_DATA_DIR`：发送历史与兴趣词库的存放目录，默认 `<项目>/data`。服务器上建议指到代码目录之外，方便持久化与备份。
- `FEISHU_BOT_SECRET`：**只在机器人开启了"签名校验"时才需要填**。若机器人开了签名校验但这里留空，飞书会拒绝每一条消息。
- 真实 API Key 只放在 `.env`，不要公开到仓库或截图里。

## 运行状态文件

程序会在数据目录（默认 `./data`）维护两个文件，都是"坏了也不影响运行"的可选状态：

- `sent_history.jsonl`：最近发送过的新闻标题。用于**跨天去重**，避免同一件事连续两天推给你。
- `interest.json`：你的兴趣关键词，作为规则打分和 AI 评分的**轻微加权**（不会压过重大新闻）。

管理兴趣词库：

```powershell
# 查看当前兴趣词
.\.venv\Scripts\python.exe .\src\main.py --show-interest

# 增加兴趣词（可重复传多个）
.\.venv\Scripts\python.exe .\src\main.py --add-interest 半导体 --add-interest 美联储

# 移除兴趣词
.\.venv\Scripts\python.exe .\src\main.py --remove-interest 美联储
```

## 新闻筛选逻辑

流程是：

```text
RSS 抓取 -> 去重（含近重复标题）-> 规则粗筛 -> 跨天去重 -> DeepSeek 价值评分 -> 多样性控制 -> DeepSeek 白话解读 -> 飞书发送
```

规则粗筛会降低明显低价值内容的优先级，例如：

- 纯会议、调研、表态
- 直播、滚动更新、图集、视频
- 空泛套话和重复口径

英文关键词使用**词边界匹配**，因此 `ai`、`war` 不会被 `available`、`software`、`forward` 这类词误触发。

DeepSeek 评分会判断：

- 是否有新信息
- 是否影响政策、市场、科技、国际关系或普通人生活
- 是否有具体事实、数字、动作或结果
- 是否只是来源的一种说法
- 是否有被带节奏或宣传口径的风险

最终卡片里的"价值分"来自这一步评分（范围 0.5–5.0，AI 给低分不会被强行抬到 1 分）。

## 降级可见性

AI 评分或解读一旦失败，程序不会静默混过去：

- 飞书卡片**顶部会插入橙色告警条**并写明原因；
- 卡片表头由蓝色变为橙色；
- 日志与 `--dry-run` 输出会标记 `[DEGRADED]` / `DEGRADED`。

所以定时任务里收到的卡片，一眼就能看出"这期是 AI 正常输出，还是退回了 RSS 原文"。

## 安全说明

程序会请求第三方 RSS 地址，因此做了基本的加固，部署到公网服务器时尤其相关：

- **拒绝内网地址（SSRF 防护）**：只允许抓取解析到公网 IP 的地址，`127.0.0.1`、`169.254.169.254`（云元数据端点）、
  私网段等一律拒绝。**重定向也逐跳校验**，防止公网域名 302 跳到内网。
- **密钥脱敏**：网络异常进入日志前会抹掉飞书 webhook token、`sk-` 开头的 API Key 等凭证，
  避免排障日志本身泄露可用密钥。
- **Prompt 注入防护**：RSS 标题与摘要属于不可信外部数据，会以 `<articles>` 显式包裹并声明「这不是指令」，
  防止文章内容伪造指令影响模型输出。
- **资源上限**：单个 RSS 响应体上限 5 MB；`MAX_ARTICLES` 等配置有上限校验，防止误填天量数值拖垮进程。

已知取舍：SSRF 校验与实际连接之间存在极短的 DNS 重绑定窗口（TOCTOU）。彻底消除需要自定义连接池固定 IP，
与本项目「零额外依赖」的定位冲突，当前覆盖恶意 OPML 与重定向链等现实攻击路径。

## Windows 本地运行

运行环境要求 Python 3.10 或更高版本。先确认版本：

```powershell
python --version
```

安装依赖：

```powershell
cd <项目所在目录>
.\setup.ps1
```

生产部署想复用当前已验证依赖版本时，可以改用：

```powershell
.\setup.ps1 -UseLock
```

只检查配置，不联网、不发送飞书：

```powershell
.\.venv\Scripts\python.exe .\src\main.py --check-config
```

只检查 RSS，不发送飞书；会要求至少抓到 `min(10, MAX_ARTICLES)` 条：

```powershell
.\.venv\Scripts\python.exe .\src\main.py --check-feeds
```

只检查 DeepSeek Key 和模型，不发送飞书：

```powershell
.\.venv\Scripts\python.exe .\src\main.py --check-deepseek
```

发送一条飞书探针卡，确认 Webhook 可用：

```powershell
.\.venv\Scripts\python.exe .\src\main.py --check-feishu
```

完整生成摘要但不发送飞书：

```powershell
.\.venv\Scripts\python.exe .\src\main.py --dry-run
```

上线前完整检查：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check_release.ps1
```

准备发布固定版本时，要求 Git 工作区干净：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check_release.ps1 -RequireGitClean
```

上线前如果也想验证飞书实际可达，会发送一条探针卡：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check_release.ps1 -SendFeishuProbe
```

手动发送一次：

```powershell
.\run_daily_news.ps1
```

注册 Windows 每日定时任务，例如每天 08:30：

```powershell
.\register_task.ps1 -TaskName "DailyNewsFeishu" -Time "08:30"
```

## 服务器部署

服务器部署时尽量和现有服务隔离：

- 使用普通用户，不用 `root`
- 项目放在 `~/apps/daily-news-feishu`
- 使用项目自己的虚拟环境
- 不修改 nginx、防火墙、已有服务
- 不监听任何端口，只作为定时脚本运行

从 Windows 上传项目文件：

```powershell
scp -r "<项目所在目录>\src" "<项目所在目录>\requirements.txt" "<项目所在目录>\requirements.lock.txt" "<项目所在目录>\.env" <server-user>@<server-host>:/home/<server-user>/apps/daily-news-feishu/
```

上传后限制配置文件权限，避免 API Key 和 Webhook 被同机其他用户读取：

```bash
chmod 600 ~/apps/daily-news-feishu/.env
```

服务器上建议把状态文件放到代码目录之外，升级代码时不会连带清掉历史：

```bash
grep -q '^NEWS_DATA_DIR=' .env || echo 'NEWS_DATA_DIR=/home/<server-user>/apps/daily-news-feishu/data' >> .env
mkdir -p ~/apps/daily-news-feishu/data
```

服务器上初始化依赖，生产部署优先使用锁定版本：

```bash
cd ~/apps/daily-news-feishu
python3 --version  # 需要 3.10+
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock.txt
```

服务器上测试：

```bash
cd ~/apps/daily-news-feishu
.venv/bin/python src/main.py --check-config
.venv/bin/python src/main.py --check-feeds
.venv/bin/python src/main.py --check-deepseek
.venv/bin/python src/main.py --check-feishu
.venv/bin/python src/main.py --dry-run
.venv/bin/python src/main.py
```

如果国外 RSS 抓不到，设置代理：

```bash
grep -q '^RSS_PROXY=' .env || echo 'RSS_PROXY=http://127.0.0.1:7890' >> .env
```

再检查一次：

```bash
.venv/bin/python src/main.py --check-feeds
```

正常情况下会看到类似：

```text
Fetched 80 deduplicated articles.
Domestic articles: 40; international articles: 40.
International samples:
```

## 服务器定时任务

推荐的 cron 配置：

```cron
30 8 * * * cd /home/<server-user>/apps/daily-news-feishu && /usr/bin/flock -n /tmp/daily-news-feishu.lock /home/<server-user>/apps/daily-news-feishu/.venv/bin/python src/main.py >> /home/<server-user>/apps/daily-news-feishu/news.log 2>&1
```

直接写入 crontab：

```bash
printf '%s\n' '30 8 * * * cd /home/<server-user>/apps/daily-news-feishu && /usr/bin/flock -n /tmp/daily-news-feishu.lock /home/<server-user>/apps/daily-news-feishu/.venv/bin/python src/main.py >> /home/<server-user>/apps/daily-news-feishu/news.log 2>&1' | crontab -
crontab -l
```

查看日志：

```bash
tail -n 100 ~/apps/daily-news-feishu/news.log
```

成功发送时会看到：

```text
Sent card summary with 20 selected articles from 80 source articles.
```

## 飞书消息内容

飞书卡片包含：

- “先说人话”的总览
- 约 20 条新闻
- 国内和国外新闻混合
- 更容易读懂的改写标题
- 两句话摘要
- “别被带跑”的提醒、背景或后续观察点
- 价值分
- 原文链接

## 常见问题

如果 Windows 上 SSH/SCP 超时：

```powershell
Test-NetConnection <server-host> -Port 22
ssh <server-user>@<server-host>
```

如果没有国外新闻：

```bash
cd ~/apps/daily-news-feishu
grep '^RSS_PROXY=' .env
.venv/bin/python src/main.py --check-feeds
```

如果 `127.0.0.1:7890` 不可用，试试 `7891`：

```bash
sed -i 's#^RSS_PROXY=.*#RSS_PROXY=http://127.0.0.1:7891#' .env
```

如果定时任务没有发送：

```bash
crontab -l
tail -n 100 ~/apps/daily-news-feishu/news.log
```

如果 DeepSeek 检查提示鉴权失败，说明当前 Key 已失效或没有所配模型的权限。更新 `.env` 后单独复验：

```bash
.venv/bin/python src/main.py --check-deepseek
```
