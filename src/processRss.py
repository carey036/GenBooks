from FeedparserThread import FeedparserThread
import keys,logging,requests,os,json,pytz,zipfile
from datetime import datetime
from PIL import Image
from bs4 import BeautifulSoup
class processRss:
    def __init__(self,start):
        self.updatenum = 0#所有的post数量，用于最后判断时候生成文件
        self.imgid = 0#mainfest文件中图片的id，在json文件生成中写入
        self.articleid = 2
        self.playorder = 2
        self.opf_mainfest = ""#opf文件中的mainfest部分 
        self.rssjson = []
        self.start = start
    def nicedate(self,dt):
        return dt.strftime('%d %B %Y').strip('0')
    def nicehour(self,dt):
        return dt.strftime('%I:%M&thinsp;%p').strip('0').lower()
    def nicepost(self,post):
        thispost = post._asdict()
        thispost['nicedate'] = self.nicedate(thispost['time'])
        thispost['nicetime'] = self.nicehour(thispost['time'])
        return thispost
    def get_posts_list(self,feed, START):
        """
        Spawn a worker thread for each feed.
        """
        posts = []
        ths = []
        th = FeedparserThread(feed, START, posts)
        ths.append(th)
        th.start()
        for th in ths:
            th.join()
        # When all is said and done,
        return posts
    def downloadimg(self,url,imgid,thisformat,compress_quality):
        headers = {
            'upgrade-insecure-requests': "1",
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.96 Safari/537.36 Edg/88.0.705.50'
        }
        with open(f"./temp/OEBPS/img{self.imgid}.{thisformat}","wb")as f:
            try:
                f.write(requests.get(url,headers=headers).content)
            except:
                logging.info(f"{self.imgid}.{thisformat}下载失败")
            f.close()
        #print("download")
        try:
            self.compress_img(f"./temp/OEBPS/img{imgid}.{thisformat}",compress_quality)
            #print("download ok")
            return True
        except:
            logging.info(f"./temp/OEBPS/img{imgid}.{thisformat}未压缩")
            os.remove(f"./temp/OEBPS/img{imgid}.{thisformat}")
            return False
    def compress_img(self,dir,compress_quality):
        img = Image.open(dir)
        img = img.convert('L')
        img.save(dir,quality=compress_quality)
    def editimg(self,originsource,compress_quality):
        '''
        传递未替换图片的htmlsource
        返回
        1. 替换了图片的imgsource
        2. mainfest 
        '''
        result={"imgsource":"","mainfest":""}
        soup = BeautifulSoup(originsource, "html.parser")
        tags = soup.find_all("img")
        for img in tags:
            #print(img['src'])
            imgformats = ["jpg","png"]
            thisformat = False
            for imgformat in imgformats:
                try:
                    if(imgformat in img['src']):
                        thisformat = imgformat
                except:#if not src attr
                    thisformat = False
            #print(thisformat)
            if(thisformat):
                #_thread.start_new_thread(downloadimg,(img['src'],imgid,thisformat,))
                if(self.downloadimg(img['src'],self.imgid,thisformat,compress_quality)):
                    img['src'] = f"./img{self.imgid}.{thisformat}"
                    mediatype={"jpg":"image/jpeg","png":"image/png"}
                    result["mainfest"]+=f' <item href="img{self.imgid}.{thisformat}" id="img{self.imgid}" media-type="{mediatype[thisformat]}" />'
                    self.imgid+=1
                else:
                    img.extract()
        result['imgsource'] = soup.prettify()
        return result
    def genjson(self,feeds):
        for feed in feeds:
            posts = self.get_posts_list(feed["url"],self.start)
            try:
                thisfeed = {"name":feed["name"],"posts":[],"css":feed["css"]}
            except:
                thisfeed = {"name":feed["name"],"posts":[],"css":""}
            if(posts):
                logging.info(f"Downloaded {len(posts)} posts")
                self.updatenum += len(posts)
                i=1
                for post in posts:
                    logging.info("开始处理第{}个post".format(str(i)))
                    i+=1
                    post = self.nicepost(post)
                    #print([post])
                    if(feed["saveimg"]==True):
                        imgmessage = self.editimg(post["body"],feed['imgquality'])
                        post["body"] = imgmessage["imgsource"]
                        self.opf_mainfest+=imgmessage["mainfest"]
                    else:
                        #需要删除img标签
                        soup = BeautifulSoup(post['body'], "html.parser")
                        tags = soup.find_all("img")
                        [tag.extract() for tag in tags]
                        post['body']=soup.prettify()
                        #print(post['body'])
                    feedmessage = {"articleid":"","title":post["title"],"content":post["body"],"date":post["nicedate"],"time":post["nicetime"],"blog":post["blog"],"author":post["author"]}
                    #print(post)
                    thisfeed["posts"].append(feedmessage)
                self.rssjson.append(thisfeed)
        return self.rssjson
    def json2epub(self,rssjsons,booktitle="RSS Daily"):
        '''
        
        '''
        epub = {"opf":"","ncx":"","toc_summary":"","feeds":[],"tocs":[]}
        feedid = 0#当前遍历的第几个feed
        opf_ncx_section=""
        opf_ncx_feed=""
        toc_summary_body = ""
        ncx_feed = ""
        #print(rssjsons)
        for rssjson in rssjsons:
            subtitle = rssjson['name']
            feed_content = ""
            toc_content = ""
            ncx_article = ""
            postnum = 0
            for post in rssjson["posts"]:
                post["articleid"]=str(self.articleid)
                self.articleid+=1
                feed_content += keys.feed_content.format(**post)
                post.update({"feedid":str(feedid)})
                toc_content += keys.toc_content.format(**post)
                post.update({"playorder":self.playorder})
                ncx_article += keys.ncx_article.format(**post)
                self.playorder += 1
                postnum += 1#计算这里面有多少篇文章
            feed_para = {"subtitle":subtitle,"feed":feed_content,"tocbody":toc_content,"css":keys.css + rssjson["css"]}
            epub["feeds"].append({"feedid":str(feedid),"content":keys.feed.format(**feed_para)})
            epub["tocs"].append({"feedid":str(feedid),"content":keys.toc.format(**feed_para)})
            feed_para.update({"postnum":postnum,"ncx_article":ncx_article,"feedid":feedid,"playorder":str(self.playorder-postnum)})
            ncx_feed += keys.ncx_feed.format(**feed_para)#每一个feed都要生成ncx，集成一个
            toc_summary_body += keys.toc_summary_body.format(**feed_para)
            self.opf_mainfest += '<item href="feed{}.html" id="feed{}" media-type="application/xhtml+xml"/>'.format(str(feedid),str(feedid))
            self.opf_mainfest+='<item href="toc_{}.html" id="section{}" media-type="application/xhtml+xml"/>'.format(str(feedid),str(feedid))
            opf_ncx_section += '<itemref idref="section{}"/>'.format(str(feedid))
            opf_ncx_feed += '<itemref idref="feed{}"/>'.format(str(feedid))
            feedid += 1
        #print(opf_ncx_section+opf_ncx_feed)
        file_para = {"booktitle":booktitle,"ncx_feed":ncx_feed,"toc_summary_body":toc_summary_body,"date":str(datetime.now(pytz.timezone('Asia/Shanghai')).strftime("%Y-%m-%d")),"opf_mainfest":self.opf_mainfest,"opf_ncx":opf_ncx_section+opf_ncx_feed}
        epub["ncx"] = keys.ncx.format(**file_para)
        epub["toc_summary"] = keys.toc_summary.format(**file_para)
        epub["opf"] = keys.opf.format(**file_para)
        return (epub)
    def save_epub(self,epubinfo,temppath="./temp/",savepath="dailyRss.epub"):
        '''
        要保证文件夹存在，且文件夹内存在其他必要文件
        '''
        # epubinfo = {"opf":"","ncx":"","toc_summary":"","feeds":[],"tocs":[]}
        with open(temppath+"OEBPS/content.opf","w",encoding='utf-8') as f:
            f.write(epubinfo["opf"])
            f.close()
        with open(temppath+"OEBPS/toc.ncx","w",encoding='utf-8') as f:
            f.write(epubinfo["ncx"])
            f.close()
        with open(temppath+"OEBPS/toc.html","w",encoding='utf-8') as f:
            f.write(epubinfo["toc_summary"])
            f.close()
        for feed in epubinfo['feeds']:
            with open(temppath+"OEBPS/feed{}.html".format(feed["feedid"]),"w",encoding='utf-8') as f:
                f.write(feed['content'])
                f.close()
        for toc in epubinfo['tocs']:
            with open(temppath+"OEBPS/toc_{}.html".format(toc["feedid"]),"w",encoding='utf-8') as f:
                f.write(toc['content'])
                f.close()
        #压缩保存
        z = zipfile.ZipFile(savepath,'w',zipfile.ZIP_DEFLATED)
        for dirpath, dirnames, filenames in os.walk(temppath):
            fpath = dirpath.replace(temppath,'') #这一句很重要，不replace的话，就从根目录开始复制
            fpath = fpath and fpath + os.sep or ''
            for filename in filenames:
                z.write(os.path.join(dirpath, filename),fpath+filename)
        z.close()
if __name__ == '__main__':
    feeds = '''
    [
    
        
    ]
    '''
    project = processRss(pytz.timezone('Asia/Shanghai').localize(datetime.fromtimestamp(1611600616)))
    project.json2epub(project.genjson(json.loads(feeds)))
