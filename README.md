# GenBooks
Gen epub and mobi Books from RSS with github action

## English Version

[English Version](./README-EN.md)

# 特点

1. 支持epub和mobi格式
2. 支持邮箱（用于kindle）和webdav以及telegram_Bot以及send2boox等多种发送方式。
3. 部署在github action，免去服务费用以及GAE部署的账号问题
4. 支持自定义下载图片以及更改图片压缩比例
5. 支持单个rss自定义css

# 使用方法

1. fork 本项目

2. 在config文件夹里替换成你的封面

3. 在项目setting里新建3个secret

   1. CONFIG

        也可以修改rss.conf进行配置，secret的优先级大于rss.conf

      使用json样式，推荐使用 https://www.json.cn/ 进行在线编辑

      ```json
      {
          "title":"you book name",
          "feeds": [
              {"name":"rss title","url":"rss url","saveimg":true,"imgquality":20},
              {"name":"rsstitle","url":"rssurl","saveimg":true,"imgquality":20,"css":"img.avatar,a.originUrl,div.view-more{display:none;}span.bio,span.author{font-size:0.7em;}div.question{margin-bottom:2cm;}"}
          ],
          "emailinfo": {
              "enable": false,
              "to": "you kindle email",
              "from": "your email which is used to send files",
              "smtp": "smtp-mail.outlook.com",
              "port": 25,
              "pwd": "",
              "epub": false,
              "mobi": true
          },
          "webdav":{
              "enable":false,
              "server":"https://your webdav adress",
              "user":"",
              "pwd":"",
              "epub": false,
              "mobi": true
          },
          "telegram":{
              "enable":false,
              "token":"bot token",
              "chat_id":"which id you want to receive messages",
              "epub":true,
              "mobi":true
          },
          "boox":{
              "enable":false,
              "token":"send2booxToken, get from cookie",
              "epub":false,
              "mobi":true
          },
          "github": {
              "enable":false,
              "epub":false,
              "mobi":false
          }
      }
      
      ```

      说明：

      1. title 为你要生成的书籍名称，feeds为你要订阅的rss信息
      2. feeds内信息说明，name为rss名称，url为rss链接，savimg为是否保存图片，imgquality为图片质量（0-100的数值），css为你要自定义的css
      3. emailinfo，webdav，telegram，boox，以及github是相应的文件发送方式，enable设置为true即可打开该发送方式，fasle即为关闭
      4. boox的token可在f12开发者模式中，通过查看cookie抓取

   2. GITHUBEMAIL 内容为你的github账户的邮箱

   3. GITHUBUSER 内容为你的github的用户名

4. 在./github/workflow里面修改想推送的时间和频率

   参考crontab

5. 打开github action，点击star进行测试

   ## CSS示例

   知乎

   `img.avatar{display:none;}`

   36kr

   `h1,h2,h3,h4,h5,h6{font-size:1em; font-weight:normal}`

   参考: https://blog.xsnet.top/shi-yong-github-action-bu-shu-rss2mobibing-fa-song-dao-kindle.html

   # 其他

   readme文档可能含有表达不清楚的地方，欢迎提交pr和issue

