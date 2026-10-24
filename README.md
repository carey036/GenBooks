# GenBooks

把 RSS 订阅源打包成 epub / mobi 电子书，通过 GitHub Actions 定时运行，并推送到 Kindle、WebDAV、Telegram、Boox 等地方。

[English Version](#english) · [从旧版升级](#从旧版升级)

---

## 特点

- **多源合并**：把多个 RSS 源合成一本「日报」，每个源是一章
- **epub / mobi 双格式**：epub 用 ebooklib 生成标准 EPUB3，mobi 由 calibre 转换
- **多渠道投递**：邮件（Kindle）、WebDAV、Telegram Bot、send2boox、GitHub 仓库
- **失败隔离**：某个渠道配错了或网络挂了，**其它渠道照常工作，已生成的书籍不会丢**
- **增量抓取**：默认只抓上次成功运行之后的新文章，不会重复推送
- **图片处理**：可选下载并压缩正文图片，自动跳过失效图片
- **单源自定义样式**：每个 RSS 源可以单独写 CSS

## 快速开始

### 1. Fork 本仓库

### 2. 写配置

把 `config/rss.conf` 改成你的订阅。最小可用配置只需要两项：

```json
{
  "title": "我的日报",
  "feeds": [
    {"name": "少数派", "url": "https://sspai.com/feed"}
  ]
}
```

> **其它段落全部可省略。** 没写的渠道自动视为关闭，不会报错。

完整配置（所有字段）：

```json
{
  "title": "我的 RSS 日报",
  "lookback_hours": 24,
  "css": "全局追加样式，可省略",
  "feeds": [
    {
      "name": "显示在书里的章节名",
      "url": "RSS 地址",
      "saveimg": true,
      "imgquality": 60,
      "css": "只对这一源生效的样式"
    }
  ],
  "email":    {"enable": false, "epub": false, "mobi": true,
               "to": "", "from": "", "smtp": "", "port": 587, "pwd": ""},
  "webdav":   {"enable": false, "epub": true, "mobi": true,
               "server": "", "user": "", "pwd": ""},
  "telegram": {"enable": false, "epub": true, "mobi": false,
               "token": "", "chat_id": ""},
  "boox":     {"enable": false, "epub": false, "mobi": true, "token": ""},
  "github":   {"enable": true,  "epub": true,  "mobi": false}
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `title` | 书名，也会用作输出文件名 |
| `lookback_hours` | 抓取最近 N 小时的文章。**省略则使用增量状态**（只抓上次运行之后的新文章） |
| `feeds[].name` | 章节标题；省略则用 RSS 源标题 |
| `feeds[].saveimg` | 是否把正文图片一起打包 |
| `feeds[].imgquality` | 图片压缩质量 0-100，越低体积越小 |
| `feeds[].css` | 只对这个源生效的 CSS |
| `*.enable` | 是否启用该渠道 |
| `*.epub` / `*.mobi` | 该渠道要推送哪些格式 |

各渠道必填项（仅在 `enable: true` 时校验）：

- `email`：`to` `from` `smtp` `port` `pwd`。端口 465 自动用 SSL，其它端口自动 STARTTLS
- `webdav`：`server` `user` `pwd`
- `telegram`：`token` `chat_id`
- `boox`：`token`（浏览器 F12 → Application → Cookies 里的 `token`）
- `github`：无必填项，把文件留在 `output/` 交给 workflow 提交

### 3. 配置 GitHub Secrets

仓库 `Settings → Secrets and variables → Actions` 里新建：

| Secret | 内容 |
|---|---|
| `CONFIG` | 把上面的 JSON **整个**粘进去（优先级高于仓库里的 `rss.conf`） |
| `GITHUBUSER` | 你的 GitHub 用户名 |
| `GITHUBEMAIL` | 你的 GitHub 邮箱 |

> 不想用 Secret 也可以直接改 `config/rss.conf` 并提交，两种方式都支持。

### 4. 手动跑一次测试

`Actions → 生成书籍 → Run workflow`，可以勾 `dry_run` 先只看生成效果、不真的推送。

## 本地运行

```bash
pip install -r requirements.txt

python3 src/genBook.py --dry-run   # 只生成不投递
python3 src/genBook.py             # 正常跑一轮
python3 src/genBook.py -v          # 调试日志
```

转换成 mobi 需要本机装 [calibre](https://calibre-ebook.com/)（提供 `ebook-convert`）。
没有 calibre 时会自动跳过 mobi，只投递 epub。

常用参数：

| 参数 | 说明 |
|---|---|
| `-c/--config` | 配置文件路径，默认 `./config/rss.conf` |
| `--dry-run` | 只生成不投递 |
| `--lookback N` | 强制回溯 N 小时（覆盖配置和状态） |
| `-o/--output` | 输出目录，默认 `./output` |
| `-v` | 详细日志 |

## 输出与退出码

- 书籍输出到 `output/`
- 退出码：`0` 成功（含「无新文章」）、`1` 有渠道投递失败、`2` 配置错误

投递结果会在日志末尾汇总：

```
投递结果汇总：
  ✓ email: 已禁用，跳过
  ✗ webdav: ConnectionError: ... connection refused
  ✓ telegram: 已发送 1 个文件到 123456
  ✓ github: 保留 1 个文件交给 workflow 提交
```

**某个渠道失败不会影响别的渠道，也不会删除已生成的书籍。**

## 项目结构

```
src/
  genBook.py            # 入口，保持原来的调用方式
  genbooks/
    config.py           # 配置归一化：缺什么补什么，绝不因缺键崩溃
    feeds.py            # RSS 抓取、时间解析、增量状态
    images.py           # 图片下载 / 压缩 / 重写正文
    builder.py          # 用 ebooklib 生成 EPUB3
    convert.py          # epub -> mobi（检查 returncode 和产物）
    delivery/
      base.py           # 渠道抽象 + 失败隔离 + 超时保护
      email.py  webdav.py  telegram.py  boox.py  github.py
    app.py              # 编排整条流水线
```

## 自定义 CSS

知乎日报：

```css
img.avatar, a.originUrl, div.view-more { display: none; }
span.bio, span.author { font-size: 0.7em; }
div.question { margin-bottom: 2cm; }
```

36氪：

```css
h1, h2, h3, h4, h5, h6 { font-size: 1em; font-weight: normal; }
```

## 从旧版升级

配置**完全向后兼容**——老的 `rss.conf` / `CONFIG` 原样能用。需要注意的变化：

| 旧版 | 新版 |
|---|---|
| `emailinfo` 段落 | 推荐改名 `email`（旧名仍兼容） |
| `config/time.txt` 写数字表示回溯小时 | 改用 `lookback_hours`；增量状态存 `config/last_run.txt` |
| 书籍输出到仓库根目录 | 统一输出到 `output/` |
| `src/sendConfig.py` | 已移除 |

## 参考

- 思路源自 [KindleEar](https://github.com/cdhigh/KindleEar)
- 部署教程：https://blog.xsnet.top/shi-yong-github-action-bu-shu-rss2mobibing-fa-song-dao-kindle.html

---

## English

GenBooks turns RSS feeds into epub/mobi ebooks, runs on GitHub Actions, and delivers them to Kindle (email), WebDAV, Telegram, Boox, or back into a Git repo.

Key points:

- **Failures are isolated.** A broken channel never stops the others and never deletes the generated book.
- **Config is forgiving.** Omitting any channel section simply disables it — no crash.
- **Incremental by default.** Only posts newer than the last successful run are fetched.

Minimal config:

```json
{"title": "My Daily", "feeds": [{"name": "Feed", "url": "https://example.com/feed"}]}
```

See the Chinese section above for the full option table; each module under `src/genbooks/delivery/` maps one-to-one to a channel.
