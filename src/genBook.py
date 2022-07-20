from email.utils import COMMASPACE, formatdate
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime, timedelta
import os,smtplib,sys,pytz,time,logging,threading,subprocess,json,requests,shutil,_thread,processRss
from boox import send2Boox
logging.basicConfig(level=logging.INFO)
def getConfig():
    ### 仅调试时使用
    with open("./config/rss.conf","r",encoding="utf8") as f:
        conf = f.read()
        f.close()
    return conf
config = os.environ.get("config")
#config = getConfig()
logging.info("loading config")
try:
    if(config):
        config = json.loads(config)
    else:
        logging.info("get env fail, try to read rss.conf")
        config = json.loads(getConfig())
except:
    logging.info("error occurred when reading config")
feeds = config["feeds"]
booktitle = config["title"]
emailInfo = config["emailinfo"]
webdavInfo = config["webdav"]
boox = config["boox"]
CONFIG_PATH = './config'
feed_file = "./config/time.txt"
source_path = os.path.abspath(r'./template')
target_path = os.path.abspath(r'./temp')
if not os.path.exists(target_path):
    # 如果目标路径不存在原文件夹的话就创建
    os.makedirs(target_path)

if os.path.exists(source_path):
    # 如果目标路径存在原文件夹的话就先删除
    shutil.rmtree(target_path)
shutil.copytree(source_path, target_path)
shutil.copy(os.path.abspath(r'./config/cover.jpg'), os.path.abspath(r'./temp/OEBPS/'))
logging.info('copy files finished!')

def get_start(fname):
    """
    Get the starting time to read posts since. This is currently saved as 
    the timestamp of the time file.
    """
    '''
    return pytz.utc.localize(datetime.fromtimestamp(os.path.getmtime(fname)))
    '''
    with open("./config/time.txt","r+") as f:
        timeStamp = int(f.read())
        #获取完start立即写入，确保时间间隔为最小
        f.seek(0)
        f.write(str(int(time.mktime(datetime.now(pytz.timezone('UTC')).timetuple()))))
        f.close()
    '''
    #获取完start立即写入，确保时间间隔为最小
    logging.info("save this stamp to file.")
    with open("./config/time.txt","w") as f:
        #f.write("1611509501")
        f.close()
    '''
    #logging.info(pytz.utc.localize(datetime.fromtimestamp(timeStamp)))
    return pytz.timezone('UTC').localize(datetime.fromtimestamp(timeStamp))
    #86400适用于每天推送一次
    #return pytz.timezone('UTC').localize(datetime.fromtimestamp(time.time()-86400))#发现有些Rss源的pubtime和显示在源上的time是不对称的，很难过，还没有想到更好的解决办法

def convert_to_mobi(input_file, output_file):
    cmd = ['ebook-convert', input_file, output_file]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    out = process.communicate()
    #print ("Result : "+out.decode() )
    #print(str(out))
    if(".mobi" in str(out)):
        logging.info("mobi created success")
    else:
        logging.info("mobi created fail")
        logging.info(out)
    if(".epub" in str(out)):
        logging.info("epub created success")
    else:
        logging.info("epub created fail")
        logging.info(out)
def sendEmail(send_from, send_to, subject, text, files):
    # assert isinstance(send_to, list)

    msg = MIMEMultipart()
    msg['From'] = send_from
    #msg['To'] = COMMASPACE.join(send_to)
    msg['To'] = send_to
    msg['Date'] = formatdate(localtime=True)
    msg['Subject'] = subject
    msg.attach(MIMEText(text, 'plain', 'utf-8'))

    for f in files or []:
        with open(f, "rb") as fil:
            msg.attach(MIMEApplication(
                fil.read(),
                Content_Disposition=f'attachment; filename="{os.path.basename(f)}"',
                Name=os.path.basename(f)
            ))
            fil.close()
    try:
        smtp = smtplib.SMTP_SSL(emailInfo["smtp"],emailInfo["port"])
    except:
        smtp = smtplib.SMTP(emailInfo["smtp"],emailInfo["port"])
    if("@outlook.com" in send_from):#outlook邮箱自动开启starttls安全验证，其他的暂不清楚
        smtp.starttls()
    logging.info(smtp.login(emailInfo["from"], emailInfo["pwd"]))
    logging.info(smtp.sendmail(send_from, send_to, msg.as_string()))
    smtp.quit()

def do_one_round():
    # get all posts from starting point to now
    start = get_start(feed_file)
    
    logging.info(f"Collecting posts since {start} UTC")
    logging.info(f"Convert Rss to json( need a long time if pic needed)")
    #generJson
    project = processRss.processRss(start)
    logging.info("RSS2Json")
    json = project.genjson(feeds)
    if(project.updatenum!=0):
        logging.info(f"发现{project.updatenum}条RSS更新，开始Json2Epub")
        epubinfo = project.json2epub(json,booktitle)
        logging.info("Epub转换成功，准备保存Epub")
        nowdate = time.strftime("%y%m%d%H",time.localtime())
        epubFile = f"{booktitle}{nowdate}.epub"
        mobiFile = F"{booktitle}{nowdate}.mobi"
        logging.info(f"删除旧的书籍(如果有)")
        if(os.path.exists(epubFile)):
            os.remove(epubFile)
        if(os.path.exists(mobiFile)):
            os.remove(mobiFile)
        project.save_epub(epubinfo,savepath="temp"+epubFile)
        convert_to_mobi("temp"+epubFile,epubFile)#转换epub以适应boox的v2引擎
        logging.info("Del Temp folder")
        shutil.rmtree("./temp/")
        logging.info("Epub2Mobi")
        convert_to_mobi("temp"+epubFile, mobiFile)
        ###################################文件创建完成，开始发送部分
        
        ##执行邮件发送动作
        logging.info("send file by email")
        try:
            if(emailInfo["enable"]==True):
                attachfile=[]
                if(emailInfo["epub"]):
                    attachfile.append(epubFile)
                if(emailInfo["mobi"]):
                    attachfile.append(mobiFile)
                sendEmail(send_from=emailInfo["from"],
                            send_to=emailInfo["to"],
                            subject="Convert",
                            text="delivery by your github action.\n\n--\n\n",
                            files=attachfile)
            else:
                logging.info("Email is disabled, skip")
        except Exception as e:
            logging.info("error when sending email: " + e )
        ##读取文件，防止删除时正在使用
        epubRB = open(epubFile,"rb")
        mobiRB = open(mobiFile,"rb")
        ##---------------------
        #执行webdav动作
        logging.info("send file by webdav")
        try:
            if(webdavInfo["enable"]==True):
                if(webdavInfo["epub"]):
                    r = requests.put(webdavInfo["server"]+epubFile, data=epubRB,auth = requests.auth.HTTPBasicAuth(webdavInfo["user"], webdavInfo["pwd"]))
                    logging.info("文件上传返回代码"+str(r.status_code))
                if(webdavInfo["mobi"]):
                    r = requests.put(webdavInfo["server"]+mobiFile, data=mobiRB,auth = requests.auth.HTTPBasicAuth(webdavInfo["user"], webdavInfo["pwd"]))
                    logging.info("文件上传返回代码"+str(r.status_code))
                logging.info("webdav上传完成")
            else:
                logging.info("webdav is disabled, skip")
        except Exception as e:
            logging.info("error when upload to webdav: " + e )
        ##执行telegram发送动作
        logging.info("upload file to telegram")
        try:
            if(config["telegram"]["enable"]==True):
                if(config["telegram"]["epub"]):
                    requests.post(f'https://api.telegram.org/bot{config["telegram"]["token"]}/sendDocument?chat_id={config["telegram"]["chat_id"]}', files = {"Document".lower(): epubRB})
                if(config["telegram"]["mobi"]):
                    requests.post(f'https://api.telegram.org/bot{config["telegram"]["token"]}/sendDocument?chat_id={config["telegram"]["chat_id"]}', files = {"Document".lower(): mobiRB})
        except Exception as e:
            logging.info("error when send to telegram: " + e )
        ##close rb open
        epubRB.close()
        mobiRB.close()
        ## 执行send2boox
        logging.info("send 2 Boox")
        try:
            if(boox["enable"]==True):
                if(boox["epub"]):
                    with open(epubFile,"rb") as f:
                        print(send2Boox(boox['token'],epubFile.encode("utf-8").decode("latin1") ,f).putFile())
                        f.close()
                if(boox["mobi"]):
                    with open(mobiFile,"rb") as f:
                        print(send2Boox(boox['token'],mobiFile.encode("utf-8").decode("latin1"),f).putFile())
                        f.close()
        except Exception as e:
            logging.info("error when send to boox: " + e )
        ##执行github动作
        ##因为github会删除文档，所以要最后执行
        logging.info("upload file to github repo")
        os.remove("temp"+epubFile)
        if(config["github"]["enable"]==False):
            os.remove(epubFile)
            os.remove(mobiFile)
            logging.info("upload is disabled, skip")
        else:
            if(config["github"]["epub"]==False):
                os.remove(epubFile)
            if(config["github"]["mobi"]==False):
                os.remove(mobiFile)
    else:
        shutil.rmtree("./temp/")
        logging.info("RSS无更新，取消执行")
    logging.info("Finished.")
if __name__ == '__main__':
    do_one_round()
