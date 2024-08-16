from fastapi import FastAPI, UploadFile, Form, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
import time
import os
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from werkzeug.utils import secure_filename
import uvicorn
import pymysql
import logging
from datetime import datetime
from typing import Optional

# 获取当前文件所在的目录
current_file_dir = os.path.dirname(os.path.abspath(__file__))

# 定义 FastAPI 应用
app = FastAPI()

# 配置
key = 'BBUPKjHjLMKGRqjaw05GZBdu7c'
UPLOAD_FOLDER = os.path.join(current_file_dir, 'uploads')  # 使用相对于代码文件的路径
VIDEO_FOLDER = os.path.join(current_file_dir, 'video')    # 使用相对于代码文件的路径
SMTP_SERVER = 'smtp.qq.com'
SMTP_PORT = 465
SMTP_USERNAME = '158316318@qq.com'
SMTP_PASSWORD = 'dxrdvslhsizfbggb'

# 确保文件夹存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(VIDEO_FOLDER, exist_ok=True)

# 日志配置
log_dir = os.path.join(current_file_dir, 'logs')  # 使用相对于代码文件的路径
try:
    os.makedirs(log_dir, exist_ok=True)
    print(f"Directory {log_dir} created successfully")
except Exception as e:
    print(f"Failed to create directory {log_dir}: {e}")

current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
log_filename = f'{log_dir}/{current_time}.log'

logger = logging.getLogger('app_logger')
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(log_filename)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

logger.info("日志系统已启动")

def con():
    try:
        connection = pymysql.connect(
            host='localhost',
            user='video_gem',
            password='n3JJZK8AnyDZEihL',
            database='video_gem'
        )
        logger.info("数据库连接成功")
        return connection
    except pymysql.MySQLError as e:
        logger.error(f"数据库连接失败: {e}")
        return None

def get_video(task_id: str):
    while True:
        payload = {
            "key": key,
            "task_id": task_id
        }
        headers = {
            'User-Agent': 'Apifox/1.0.0',
            'Content-Type': 'application/json'
        }

        try:
            res = requests.post("https://duomiapi.com/api/video/runway/feed", json=payload, headers=headers)
        except requests.RequestException as e:
            logger.error(f"请求视频生成状态失败: {e}")
            time.sleep(30)
            continue

        try:
            data = res.json()
        except ValueError:
            logger.error(f"解析JSON响应失败: {res.text}")
            time.sleep(30)
            continue

        logger.info(f"Checking status for task_id {task_id}: {data}")
        if data['data']['status'] == '2':
            logger.error(f"task_id 为 {task_id} 的任务终止运行。错误信息：{data['data']['msg']}")
            return None
        if data['data']['video_url'] is not None:
            logger.info(f"Video generated successfully: {data['data']['video_url']}")
            return data['data']['video_url']
        time.sleep(30)

def gen_video(image_url, prompt, seconds):
    logger.info(f"开始生成视频，prompt: {prompt}")
    while True:
        payload = {
            "key": key,
            "callback_url": "https://baidu.com",
            "image": image_url,
            "style": "cinematic",
            "model": "gen3",
            "prompt": prompt,
            "options": {
                "seconds": seconds,
                "motion_vector": {
                    "x": -6.2,
                    "y": 0,
                    "z": 0,
                    "r": 0,
                    "bg_x_pan": 0,
                    "bg_y_pan": 0
                }
            }
        }
        headers = {
            'User-Agent': 'Apifox/1.0.0',
            'Content-Type': 'application/json'
        }

        try:
            res = requests.post("https://duomiapi.com/api/video/runway/pro/generate", json=payload, headers=headers)
        except requests.RequestException as e:
            logger.error(f"提交视频生成请求失败: {e}")
            time.sleep(10)
            continue

        try:
            data = res.json()
        except ValueError:
            logger.error(f"解析JSON响应失败: {res.text}")
            time.sleep(10)
            continue

        if data['code'] == 200:
            logger.info(f"API 请求成功，task_id: {data['data']['task_id']}")
            return data['data']['task_id']
        else:
            logger.error(f"API 返回错误: {data}")
            return None

def download_video(video_url, filename):
    logger.info(f"开始下载视频: {video_url}")
    try:
        video_response = requests.get(video_url)
        video_response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"下载视频失败: {e}")
        return None

    video_path = os.path.join(VIDEO_FOLDER, filename)
    try:
        with open(video_path, 'wb') as f:
            f.write(video_response.content)
        logger.info(f"视频下载成功，保存路径: {video_path}")
        return video_path
    except IOError as e:
        logger.error(f"保存视频失败: {e}")
        return None

def send_email_with_attachment(to_email, subject, body, attachment_path=None):
    msg = MIMEMultipart()
    msg['From'] = SMTP_USERNAME
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))
    if attachment_path is not None:
        try:
            with open(attachment_path, 'rb') as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(attachment_path)}')
                msg.attach(part)
        except IOError as e:
            logger.error(f"读取附件失败: {e}")

    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_USERNAME, to_email, msg.as_string())
        server.quit()
        logger.info(f"邮件发送成功，收件人: {to_email}")
    except smtplib.SMTPException as e:
        logger.error(f"发送邮件失败: {e}")

def run_task(task_id, email, image_url, prompt, seconds, tim):
    # 下载视频并保存到服务器
    video_url = get_video(task_id)
    if video_url is None:
        logger.warning(f"初次获取视频失败，重新生成视频 task_id: {task_id}")
        time.sleep(10)
        task_id = gen_video(image_url, prompt, seconds)
        video_url = get_video(task_id)
        if video_url is None:
            send_email_with_attachment(email, 'AI生成视频错误报告', f'生成prompt为{prompt}的视频时，出现错误。')
            return

    logger.info(f"视频下载地址: {video_url}")
    video_filename = f'{time.time()}.mp4'
    video_path = download_video(video_url, video_filename)

    if video_path is None:
        send_email_with_attachment(email, 'AI生成视频错误报告', f'生成prompt为{prompt}的视频时，下载视频失败。')
        return

    # 发送邮件
    tim = time.time() - tim
    logger.info(f"使用{tim}s的时间完成了任务 {task_id}")
    c = con()
    if c is not None:
        try:
            with c.cursor() as cursor:
                cursor.execute(f'update tasks set completed = 1 where task_id = "{task_id}"')
                c.commit()
        except pymysql.MySQLError as e:
            logger.error(f"更新任务状态失败: {e}")
        finally:
            c.close()
    send_email_with_attachment(email, '您的ai视频已生成请查收', '请查收附件中的视频文件。', video_path)

@app.get('/api/run-before')
async def start(bgt: BackgroundTasks):
    c = con()
    if c is None:
        raise HTTPException(status_code=500, detail="数据库连接失败")

    try:
        with c.cursor() as cursor:
            cursor.execute(f'select * from tasks where completed = 0')
            results = cursor.fetchall()
            logger.info(results)
            for task_id, image_url, prompt, email, seconds, _ in results:
                tim = time.time(0)
                bgt.add_task(run_task, task_id, email, image_url, prompt, seconds, tim)
    except pymysql.MySQLError as e:
        logger.error(f"查询未完成任务失败: {e}")
        raise HTTPException(status_code=500, detail="查询未完成任务失败")
    finally:
        c.close()

    return {'success': True}

@app.get('/api/allow-email')
def allow(request: Request, email: str):
    cookie = request.cookies
    if 'allow_email' not in cookie or cookie['allow_email'] != 'super_user:114514hello1231919810':
        return JSONResponse(status_code=403, content={'err': '您无权限！'})
    c = con()
    if c is None:
        raise HTTPException(status_code=500, detail="数据库连接失败")
    try:
        with c.cursor() as cursor:
            cursor.execute(f'select allow from allow where email = "{email}"')
            results = cursor.fetchall()
            if len(results) == 0:
                cursor.execute(f'insert into allow (email, allow) values("{email}", 1)')
                c.commit()
                return {'err': "ok"}
            else:
                if results[0][0] == 1:
                    return JSONResponse(status_code=114, content={'err': '您的邮箱已经被授权！'})
                else:
                    cursor.execute(f'update allow set allow = 1 where email = "{email}"')
                    c.commit()
                    return {'err': 'ok'}
    except pymysql.MySQLError as e:
        logger.error(f"更新授权信息或插入新邮箱失败: {e}")
        raise HTTPException(status_code=500, detail="操作数据库失败")
    finally:
        c.close()

@app.post("/api/generate-video")
async def generate_video(bgt: BackgroundTasks, image: UploadFile, prompt: Optional[str] = Form(''), seconds: int = Form(...),
                         email: str = Form(...)):
    if not image or not seconds or not email:
        raise HTTPException(status_code=400, detail="缺少必填字段")
    c = con()
    if c is None:
        raise HTTPException(status_code=500, detail="数据库连接失败")
    try:
        with c.cursor() as cursor:
            cursor.execute(f'select allow from allow where email = "{email}"')
            results = cursor.fetchall()
            if not results or results[0][0] == 0:
                return JSONResponse(status_code=403, content={'err': '您的邮箱没有被授权！'})
    except pymysql.MySQLError as e:
        logger.error(f"查询授权信息失败: {e}")
        raise HTTPException(status_code=500, detail="查询授权信息失败")
    finally:
        c.close()

    logger.info(f"秒数: {seconds}")
    # 保存上传的图片
    image_filename = secure_filename(str(time.time()) + '.jpg')
    image_path = os.path.join(UPLOAD_FOLDER, image_filename)

    try:
        with open(image_path, "wb") as buffer:
            buffer.write(await image.read())
        logger.info(f"上传图片保存成功，路径: {image_path}")
    except IOError as e:
        logger.error(f"保存上传图片失败: {e}")
        raise HTTPException(status_code=500, detail="保存上传图片失败")

    # 拼接图片的公开 URL
    image_url = f"https://video.digilifeform.com/hello/uploads/{image_filename}"

    # 生成视频
    tim = time.time()
    task_id = gen_video(image_url, prompt, seconds)

    if task_id:
        bgt.add_task(run_task, task_id, email, image_url, prompt, seconds, tim)
        c = con()
        if c is None:
            raise HTTPException(status_code=500, detail="数据库连接失败")
        try:
            with c.cursor() as cursor:
                cursor.execute(
                    'insert into tasks (task_id, image_url, prompt, email, seconds) values (%s, %s, %s, %s, %s)', 
                    (task_id, image_url, prompt, email, seconds)
                )
                c.commit()
                logger.info(f"任务插入成功，task_id: {task_id}")
        except pymysql.MySQLError as e:
            logger.error(f"插入新任务失败: {e}")
            raise HTTPException(status_code=500, detail="插入新任务失败")
        finally:
            c.close()
        return JSONResponse(content={"success": True})
    else:
        return JSONResponse(content={"success": False, "message": "生成视频失败"})

if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=5001,
                ssl_keyfile='/www/server/panel/vhost/ssl/video.digilifeform.com/privkey.pem',
                ssl_certfile='/www/server/panel/vhost/ssl/video.digilifeform.com/fullchain.pem')
