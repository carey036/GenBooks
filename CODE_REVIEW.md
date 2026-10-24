# GenBooks 代码体检报告

审查对象：`carey036/GenBooks` @ `e1790c2`（main 分支）
审查方式：通读全部源码 + **本地实跑复现**（本地搭 RSS/图片 HTTP 服务，用桩程序替换 `ebook-convert`，跑通 `do_one_round()` 全流程）

> 结论先说：项目**功能是能用的**，主体逻辑没问题（epub 结构、图片下载压缩、多源合并、TOC/NCX 都实测正常）。
> 但有一批**会静默吃掉功能**的缺陷 —— 最要命的是**只要任何一个发送渠道的配置有问题，整个投递环节会被跳过，而任务却可能显示"成功"**。

---

## 一、严重问题（建议优先修）

### 🔴 P0-1 配置缺键 → 所有投递渠道被静默跳过，构建产物丢失

`src/genBook.py` 用 `config["xxx"]` 直接取值，**没有默认值**。只要用户少写一个 `telegram` / `boox` 段落（很常见——不用这个渠道就不写），就会 `KeyError`。

更糟的是这个 `KeyError` 发生在 `try` 里，紧接着的异常处理行本身又是坏的（见 P0-2），于是整个 `do_one_round()` 直接崩溃。

**实测复现**（配置里省略 `telegram` 段）：

```
KeyError: 'telegram'
...
  File "./src/genBook.py", line 197, in do_one_round
    logging.info("error when send to telegram: " + e )
TypeError: can only concatenate str (not "KeyError") to str
exit code = 1
```

后果：书已经生成好了，但**邮件 / WebDAV / Telegram / Boox / GitHub 上传全部没执行**，且产物在进程退出时被丢弃。用户只看到 action 红了，不知道为什么。

**修法**：所有可选配置用 `.get()` + 默认值兜底，最好写个 `normalize_config()` 统一补齐默认段。

---

### 🔴 P0-2 `"字符串" + 异常对象` → 掩盖真实错误

共 4 处：`genBook.py` 第 168、187、197、215 行附近。

```python
except Exception as e:
    logging.info("error when sending email: " + e )   # ← TypeError
```

Python 不允许 `str + Exception`，所以**只要真的出异常，日志里看到的永远是 `TypeError`，而不是真实原因**。等于把所有错误诊断能力都废掉了。

**修法**：统一改成 f-string `f"...: {e}"`。

---

### 🔴 P0-3 `temp` 目录处理顺序错乱，产物路径靠字符串拼接

`genBook.py` 里：

```python
epubFile = f"{booktitle}{nowdate}.epub"
project.save_epub(epubinfo, savepath="temp"+epubFile)   # 想写进 ./temp/，实际写成了根目录 "temp{书名}.epub"
convert_to_mobi("temp"+epubFile, epubFile)
convert_to_mobi("temp"+epubFile, mobiFile)              # ← 此时 ./temp/ 已经被 rmtree 了
...
os.remove("temp"+epubFile)                              # ← 同上，路径是错的
```

问题有三层：

1. `"temp"+epubFile` 是**字符串拼接没有分隔符**，生成的是 `temp书名.epub`（仓库根目录），不是 `./temp/书名.epub` —— 文件名依赖"书名恰好让路径有效"，书名里带 `/` 或特殊字符就会炸。
2. `shutil.rmtree("./temp/")` 在两次 `convert_to_mobi` 之间执行，第二次转换的输入目录已被删除（只是因为第 1 点的路径错误"恰好"没受影响）。
3. `os.remove("temp"+epubFile)` 删的不是 temp 里的中间文件。

**修法**：全程用 `os.path.join(..., "temp", ...)` / `pathlib.Path`，并把 `rmtree` 挪到最后一次转换之后。

---

### 🟠 P0-4 转换成功与否的判断是错的

```python
out = process.communicate()
if(".mobi" in str(out)):        # 看的是输出里有没有 ".mobi" 字样
```

`communicate()` 返回 `(stdout, stderr)` 元组，实际是 `(b'', None)`。判断"输出里是否包含 `.mobi` 字符串"和"转换是否成功"毫无关系。而真正的成功信号 `process.returncode` **完全没被检查**。

**实测日志**（转换明明完成了，仍报失败）：

```
INFO:root:mobi created fail
INFO:root:(b'', None)
INFO:root:epub created fail
```

更危险的是它**只打日志、不中断**，所以转换失败时会继续往下走，拿一个不存在的文件去发邮件/上传。

**修法**：检查 `returncode == 0` 且目标文件确实存在；失败就抛异常，不要带病往下走。

---

### 🟠 P0-5 `boox.py` 用 `except:` 吞掉一切 + `fileName.split(".")[1]`

```python
fileType = self.fileName.split(".")[1]
```

文件名多于一个点（`My.Book.261024.epub`）→ 取到的是 `Book`；没有点 → `IndexError`。整个类又全是裸 `except: return("")`，失败时无声无息。

**修法**：`os.path.splitext()` 取扩展名；裸 `except` 收窄为具体异常并记日志。

---

## 二、中等问题

### 🟡 P1-1 生成的 epub 不符合 EPUB OCF 规范

实测第一个 entry 是 `mimetype` 但**被 DEFLATE 压缩了**：

```
first entry : mimetype
compress    : 8   (0=STORED 才是规范要求的)
mimetype    : b'application/epub+zip'
```

OCF 规范要求 `mimetype` 必须是**第一个且不压缩（STORED）**的 entry。部分严格的阅读器 / 校验工具会拒绝。

**修法**：`z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)` 先单独写入。

---

### 🟡 P1-2 依赖没有版本约束，且未锁死

`.github/workflows/jobs.yml` 里 `pip3 install requests` 等 6 条，全部装最新版。`feedparser` / `oss2` 等上游大版本一变，action 随时可能莫名其妙挂掉。另外 `setuplib` 那一步还 `sudo apt update && apt install libegl1 libopengl0`，跟 calibre 安装一起重复/冗余。

**修法**：建 `requirements.txt` 固定版本。

### 🟡 P1-3 GitHub Actions 版本过时

- `actions/checkout@v2`、`actions/setup-python@v2` → 均已过时（Node16 runtime，GitHub 已标记 deprecated），建议 `@v4` / `@v5`。
- `readConfig.yml` 用 `python-version: 3.9.1`（写死补丁号，已 EOL），`jobs.yml` 用 `3.10.x`，两处不一致。
- `git push origin main` 在定时任务里硬编码分支名，fork 后若默认分支不是 main 会失败。

### 🟡 P1-4 `time.txt` 语义混乱，且"相对小时数"模式不落盘

- 值 `< 10000` 时解释为"回溯 N 小时"，否则当作绝对时间戳。
- 只有绝对时间戳分支会回写新的时间戳；**"回溯 N 小时"模式永远不回写**。所以用户若按 README 说的写 `24`，每次都会回溯 24 小时 → **同一批文章每天重复推送，不会去重**。
- 用 `pytz.timezone('UTC').localize(datetime.now(...))` 再 `time.mktime` 计算，跨时区/夏令时下容易偏。这里 `time.time()` 就够了。

### 🟡 P1-5 时区处理有隐藏 bug（当前 CI 下未触发）

`FeedparserThread.process_entry()` 用 `time.mktime(when)` 处理 `struct_time` —— `mktime` 把入参当**本地时间**。GitHub runner 默认 UTC，所以现在误差是 0；本地跑或设置 `TZ` 就会偏移：

```
TZ=Asia/Shanghai: skew = -8.0 小时   （文章被判成 8 小时前，可能漏抓或误抓）
```

**修法**：用 `calendar.timegm(when)`（这正是那个未合并分支 `claude/code-optimization-review-tyABJ` 已经修对的一点）。

### 🟡 P1-6 `downloadimg` 的 id 不一致隐患

`downloadimg(url, imgid, ...)` 里写文件用 `self.imgid`，压缩和删除却用参数 `imgid`。当前调用处两者恰好相等，但一旦有并发（文件里就躺着一行注释掉的 `_thread.start_new_thread(downloadimg, ...)`）就会错乱。函数还有一个永远走不到的 `thisformat = False` 分支。

---

## 三、小问题 / 清洁度

| 位置 | 问题 |
|---|---|
| `genBook.py` | `mobiFile = F"..."` —— 大写 `F`（能用，但明显是 `f` 的笔误） |
| `genBook.py` | `getConfig()` 在模块级被注释掉，`COFIG_PATH` 定义了没用 |
| `genBook.py` | 模块级直接执行 `copytree`/`copy` 等副作用，import 即触发，难以测试 |
| `genBook.py` | `webdav` 用 `requests.put(..., data=文件对象)`，超时用 `connect_timeout` 之外没设 `timeout`，可能挂死 |
| 全部文件 | 大量 `try/except: pass` 和裸 `except`，吞异常 |
| `processRss.py` | 到处 `f.close()`（`with` 已自动关闭，多余） |
| `processRss.py` | `save_epub` 里 `dirpath.replace(temppath, '')` 拼压缩包内路径，依赖字符串替换，不如 `os.path.relpath` |
| `boox.py` | 底部 `if __name__ == '__main__'` 里写死了一个 token |
| `config/rss.conf` | 提交了示例 token（虽然是假的，但容易让人误以为要填在那里） |
| `keys.py` | `toc` / `toc_summary` 模板里有大量不换行空格(U+00A0) |
| 仓库 | 没有 `requirements.txt`，没有 `.gitignore` 覆盖 `temp*/` 和生成的书 |

---

## 四、关于已有的那个分支

`origin/claude/code-optimization-review-tyABJ` 有一个 `fix: 修复多处 bug` 的提交。它做的是**代码风格清理**：删掉多余的 `f.close()`、把 `except:` 改成 `except Exception as e`、把 `"str"+e` 改成 f-string、`calendar.timegm` 修时区。

**但它漏掉了所有 P0**：配置缺键、转换判断、`"temp"+` 路径拼接、`temp` 目录删除顺序、epub mimetype 压缩 —— 一个都没碰。其中 `timegm` 和 f-string 那两处是改对的，值得保留。**建议不要直接合并它，而是把这些正确的改动吸收到一次完整修复里。**

---

## 五、建议的修复顺序

1. **P0-1 + P0-2**：配置默认值 + 修好所有 `"str"+e` —— 收益最大，40 行以内。
2. **P0-3 + P0-4**：路径统一用 `pathlib`/`os.path.join`，转换改用 `returncode` 判断并失败即抛。
3. **P0-5**：`boox.py` 扩展名与异常收窄。
4. **P1-1**：epub mimetype 用 STORED 写入。
5. **P1-2 + P1-3**：加 `requirements.txt`，升 Actions 版本。
6. **P1-4 + P1-5**：`time.txt` 语义理顺 + `calendar.timegm`。
7. 清洁度收尾。

---

## 六、附：本次复现环境说明

- 本地起 `http.server` 提供测试 RSS 与图片；用桩程序替换 `ebook-convert`（真 calibre 体积太大）。
- 真实网络抓取（rsshub.app）未测试 —— 本机直连不通。
- **未对仓库做任何修改**，停在 `e1790c2`。
