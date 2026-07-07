# 每日新闻飞书机器人

这个项目会抓取 RSS 新闻，用 DeepSeek 做“新闻价值评分”和中文解读，然后每天发送到飞书机器人。

当前版本更偏“给自己看”的新闻解释，而不是官方通稿式摘要：

- 先抓较多候选新闻，再筛出约 20 条真正值得看的内容
- 不是只靠关键词，而是“规则粗筛 + DeepSeek 语义评分 + 多样性控制”
- 国内和国外新闻会尽量均衡
- 标题会改写得更像人话
- 摘要优先解释“到底发生了什么”
- 会提醒哪些只是来源说法，不直接当成事实
- 对官话、套话、商业话术、政治表演可以轻微调侃
- 飞书卡片会显示“价值分”

## 文件说明

- `src/main.py`：主程序
- `.env.example`：环境变量模板
- `requirements.txt`：Python 依赖
- `requirements.lock.txt`：已验证依赖锁定版本，生产部署优先使用
- `check_release.ps1`：上线前检查脚本
- `setup.ps1`：Windows 本地创建虚拟环境并安装依赖
- `run_daily_news.ps1`：Windows 本地手动运行一次
- `register_task.ps1`：Windows 本地注册定时任务

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
- 真实 API Key 只放在 `.env`，不要公开到仓库或截图里。

## 新闻筛选逻辑

流程是：

```text
RSS 抓取 -> 去重 -> 规则粗筛 -> DeepSeek 价值评分 -> 多样性控制 -> DeepSeek 白话解读 -> 飞书发送
```

规则粗筛会降低明显低价值内容的优先级，例如：

- 纯会议、调研、表态
- 直播、滚动更新、图集、视频
- 空泛套话和重复口径

DeepSeek 评分会判断：

- 是否有新信息
- 是否影响政策、市场、科技、国际关系或普通人生活
- 是否有具体事实、数字、动作或结果
- 是否只是来源的一种说法
- 是否有被带节奏或宣传口径的风险

最终卡片里的“价值分”来自这一步评分。

## Windows 本地运行

安装依赖：

```powershell
cd C:\Users\Lenovo\Desktop\daily-news-feishu
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
scp -r "C:\Users\Lenovo\Desktop\daily-news-feishu\src" "C:\Users\Lenovo\Desktop\daily-news-feishu\requirements.txt" "C:\Users\Lenovo\Desktop\daily-news-feishu\requirements.lock.txt" "C:\Users\Lenovo\Desktop\daily-news-feishu\.env" <server-user>@<server-host>:/home/<server-user>/apps/daily-news-feishu/
```

服务器上初始化依赖，生产部署优先使用锁定版本：

```bash
cd ~/apps/daily-news-feishu
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
