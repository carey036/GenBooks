# GenBooks

Gen epub and mobi Books from RSS with github action

## 中文版

[中文说明](./README.md)

# Character

1. Both epub and mobi are supported
2. support sending by email, webdav, telegram_bot, send2boox, etc
3. deployed in github action, it's free and easy
4. Support custom download pictures and change the picture compression ratio
5. Support custom css for each rss

# Steps

1. fork this project

2. Replace with your cover in the config folder 

3. create 3 secrets in Setting -> Secrets -> New repository secret

   1. CONFIG
   
        you can also setup by edit rss.conf under src, Secret takes precedence over rss.conf

      Edited with json format, you can check you edition by  https://www.json.cn/ 

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

      1. title is you book's name，feeds contains rss info which you wanna subscript
      2. Information description in feeds, name is rss's name, url is rss's adress，savimg is whether save img(true or false), imgquality is the quality of the img you want you save, css is your custom rss for this rss
      3. emailinfo, webdav, telegram, boox, and github is the way to send file, you can enable the by setting the value of enable to true, disable by false
      4. you can get the boox token by f12

   2. GITHUBEMAIL , content is your github email

   3. GITHUBUSER , content is your github username

4. edit ./github/workflow, revise schedule time

   ref crontab

5. enable github action, and do a test by clicking star

   ## Example for Css

   Zhihu

   `img.avatar{display:none;}`

   36kr

   `h1,h2,h3,h4,h5,h6{font-size:1em; font-weight:normal}`

   ref: https://blog.xsnet.top/shi-yong-github-action-bu-shu-rss2mobibing-fa-song-dao-kindle.html

   # Other

   The English version has been translated by my plastic English, please submit an issue and pr for any inaccuracy 

