import requests,json,logging,os
logging.basicConfig(level=logging.INFO)
config = os.environ.get("config")
if(config):
    with open("config.txt","w") as f:
        f.write(config)
        f.close()
    config = json.loads(config)
    logging.info("upload file to telegram")
    try:
        if(config["telegram"]["enable"]==True):
            requests.post(f'https://api.telegram.org/bot{config["telegram"]["token"]}/sendDocument?chat_id={config["telegram"]["chat_id"]}', files = {"Document".lower(): open("config.txt","rb")})
    except Exception as e:
        logging.info("error when send to telegram: " + e )

