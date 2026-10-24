"""GenBooks —— 把 RSS 打包成 epub/mobi 并投递。

分层结构：
    config   配置归一化与校验（缺键不崩，统一的默认值）
    feeds    RSS 抓取与文章解析
    builder  epub 构建（基于 ebooklib，产出规范 EPUB3）
    convert  epub -> mobi 转换（calibre）
    delivery 各投递渠道，互相隔离
    app      编排整条流水线
"""

__version__ = "2.0.0"
