import requests,json,oss2,random
class send2Boox:
    def __init__(self,token,fileName,fileData):
        self.s = requests.session()
        self.fileName = fileName
        self.fileData = fileData
        self.token = token
        self.headers = {
            "boox":{
                #GET /api/1/users/me HTTP/1.1
                'Host': 'send2boox.com',
                'Connection': 'keep-alive',
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {self.token}',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.72 Safari/537.36 Edg/89.0.774.45',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'Referer': 'https://send2boox.com/',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,pl;q=0.5,ja;q=0.4',
                'Cookie': f'locale=zh-cn; token={self.token}; language=zh'
            },
            "push":{
                #GET /api/1/users/me HTTP/1.1
                'Content-Type': 'application/json;charset=UTF-8',
                'Origin': 'https://send2boox.com',
                'Host': 'send2boox.com',
                'Content-Length': "",
                'Connection': 'keep-alive',
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {self.token}',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.72 Safari/537.36 Edg/89.0.774.45',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'Referer': 'https://send2boox.com/',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,pl;q=0.5,ja;q=0.4',
                'Cookie': f'locale=zh-cn; token={self.token}; language=zh'
            },
            "aliyun":{
                # OPTIONS /5fe28a3b6d13b4772ab7884d/push/a1ffc6b8a71250f309521267c3c24028.py HTTP/1.1
                'Host': 'onyx-cloud.oss-cn-shenzhen.aliyuncs.com',
                'Connection': 'keep-alive',
                'Accept': '*/*',
                'Access-Control-Request-Method': 'PUT',
                'Access-Control-Request-Headers': 'authorization,x-oss-date,x-oss-security-token,x-oss-user-agent',
                'Origin': 'https://send2boox.com',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.72 Safari/537.36 Edg/89.0.774.45',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'cross-site',
                'Sec-Fetch-Dest': 'empty',
                'Referer': 'https://send2boox.com/',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,pl;q=0.5,ja;q=0.4'
            }
        }
        self.fuid = self.uuid()  
    def s4(self):
        return hex(int((1+random.random()*65536)))[2:]
    def uuid(self):
        return self.s4()+self.s4()+self.s4()+self.s4()+self.s4()+self.s4()+self.s4()+self.s4()
    def guid(self):
        return self.s4()+self.s4()+"-"+self.s4()+"-"+self.s4()+"-"+self.s4()+"-"+self.s4()+self.s4()+self.s4()
    def getUid(self):
        url = "https://send2boox.com/api/1/users/me"
        try:
            return(self.s.get(url,headers=self.headers['boox']).json()['data']['uid'])
        except:
            return("")
    def getSToken(self):
        url = "https://send2boox.com/api/1/config/stss"
        result = self.s.get(url,headers=self.headers['boox']).json()["data"]
        if("AccessKeyId" in result):
            return result
        else:
            return {}
    def putFile(self):
        filePath = f'{self.getUid()}/push/{self.fuid}.py'
        url = "https://onyx-cloud.oss-cn-shenzhen.aliyuncs.com/"+filePath
        sToken = self.getSToken()
        #print(sToken)
        auth = oss2.StsAuth(sToken['AccessKeyId'],sToken['AccessKeySecret'],sToken['SecurityToken'],auth_version="AUTH_VERSION_1")
        ossinfo = self.s.get("https://send2boox.com/api/1/push/bucket",headers=self.headers['boox']).json()['data']
        bucket = oss2.Bucket(auth,"http://oss-cn-shenzhen.aliyuncs.com",ossinfo['bucket'],connect_timeout=30)
        uri = bucket.sign_url("PUT",filePath,300)
        #print(uri)
        if(self.s.options(url,headers = self.headers["aliyun"]).status_code == 200):
            try:
                result = self.s.put(uri,data=self.fileData).text
                print(result)
            except:
                print(filePath)
        #save and push
        #pushData = 
        fileType = self.fileName.split(".")[1]
        dataTemplate = '"name":"{fname}","resourceDisplayName":"{fname}","resourceKey":"{resourceKey}","bucket":"onyx-cloud","resourceType":"{fileType}","title":"{fname}","parent":null'
        dataTemplate = dataTemplate.format(fname=self.fileName,resourceKey=filePath,fileType=fileType)
        data = '{"data":{'+dataTemplate+"}}"
        #print(str(data))
        self.headers['push']['Content-Length']=str(len(str(data)))
        #print(self.headers['push'])
        try:
            if("SUCCESS" in self.s.post("https://send2boox.com/api/1/push/saveAndPush",headers=self.headers['push'],data=data).json()['message']):
                return(True)
            else:
                return(False)
        except:
            return(False)
if __name__ == '__main__':
    token = ".-0xpMNg"
    f=open("123.pdf","rb")
    print(send2Boox(token,"123.pdf".encode("utf-8").decode("latin1"),f).putFile())