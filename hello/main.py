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
import json
from json import JSONDecodeError
from email.header import Header
from email.utils import formataddr
import configparser


# Get the directory of the current file
current_file_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_file_dir)

# Define the FastAPI application
app = FastAPI()

# Read configuration file
config = configparser.ConfigParser()
config.read_string('[DEFAULT]\n' + open('config.txt').read())

# Configuration
key = config.get('DEFAULT', 'DUOMI_API_KEY')  # This is the Duomi API key
word = config.get('DEFAULT', 'AUTH_WORD')  # This is the password used to quickly authorize an email to use

UPLOAD_FOLDER = os.path.join(parent_dir, 'uploads')  # Use a path relative to the code file
VIDEO_FOLDER = os.path.join(parent_dir, 'video')     # Use a path relative to the code file

# SMTP Configuration
SMTP_SERVER = config.get('DEFAULT', 'SMTP_SERVER')
SMTP_PORT = config.getint('DEFAULT', 'SMTP_PORT')
SMTP_USERNAME = config.get('DEFAULT', 'SMTP_USERNAME')
SMTP_PASSWORD = config.get('DEFAULT', 'SMTP_PASSWORD')

# Ensure the folders exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(VIDEO_FOLDER, exist_ok=True)

# Logging configuration
log_dir = os.path.join(current_file_dir, 'logs')  # Use a path relative to the code file
try:
    os.makedirs(log_dir, exist_ok=True)
    print(f"Directory {log_dir} created successfully!")
except Exception as e:
    print(f"Failed to create directory: {log_dir}. Error: {e}")

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

logger.info("Logging system initialized")


def con():
    try:
        connection = pymysql.connect(
            host=config.get("DEFAULT", 'host'),
            user=config.get('DEFAULT', "user"),
            password=config.get('DEFAULT', 'password'),
            database=config.get('DEFAULT', 'database')
        )
        logger.info("Database connected successfully")
        return connection
    except pymysql.MySQLError as e:
        logger.error(f"Database connection failed: {e}")
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
            logger.error(f"Failed to request video generation status: {e}")
            time.sleep(30)
            continue

        try:
            data = res.json()
        except ValueError:
            logger.error(f"Failed to parse JSON response: {res.text}")
            time.sleep(30)
            continue

        logger.info(f"Checking status for task_id {task_id}: {data}")
        if data['data']['status'] == '2':
            logger.error(f"The task with task_id {task_id} was terminated. Error message: {data['data']['msg']}")
            return None
        if data['data']['video_url'] is not None:
            logger.info(f"Video generated successfully: {data['data']['video_url']}")
            return data['data']['video_url']
        time.sleep(30)


def gen_video(image_url, prompt, seconds):
    logger.info(f"Starting video generation, prompt: {prompt}")
    while True:
        payload = {
            "key": key,
            "callback_url": "https:www.baidu.com",  # This is only useful when using the Duomi API callback interface. If you don't understand it, don't modify.
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
            logger.error(f"Failed to submit video generation request: {e}")
            time.sleep(10)
            continue

        try:
            data = res.json()
        except ValueError:
            logger.error(f"Failed to parse JSON response: {res.text}")
            time.sleep(10)
            continue

        if data['code'] == 200:
            logger.info(f"API request successful, task_id: {data['data']['task_id']}")
            return data['data']['task_id']
        else:
            logger.error(f"API returned an error: {data}")
            return None


def download_video(video_url, filename):
    logger.info(f"Starting to download video: {video_url}")
    try:
        video_response = requests.get(video_url)
        video_response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to download video: {e}")
        return None

    video_path = os.path.join(VIDEO_FOLDER, filename)
    try:
        with open(video_path, 'wb') as f:
            f.write(video_response.content)
        logger.info(f"Video downloaded successfully, saved at: {video_path}")
        return video_path
    except IOError as e:
        logger.error(f"Failed to save video: {e}")
        return None


def send_email_with_attachment(to_email, subject, body, attachment_path=None):
    msg = MIMEMultipart()
    msg['From'] = formataddr((str(Header('AI Video Generator', 'utf-8')), SMTP_USERNAME))
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))
    if attachment_path is not None:
        try:
            with open(attachment_path, 'rb') as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
                encoders.encode_base64(part)
                
                # MIME encode the file name
                encoded_filename = Header(os.path.basename(attachment_path), 'utf-8').encode()
                part.add_header('Content-Disposition', f'attachment; filename="{encoded_filename}"')
                
                msg.attach(part)
        except IOError as e:
            logger.error(f"Failed to read the attachment: {e}")

    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_USERNAME, to_email, msg.as_string())
        server.quit()
        logger.info(f"Email sent successfully to: {to_email}")
    except smtplib.SMTPException as e:
        logger.error(f"Failed to send email: {e}")


def run_task(task_id, email, image_url, prompt, seconds, tim):
    # Download video and save to server
    video_url = get_video(task_id)
    if video_url is None:
        logger.warning(f"Failed to get video for the first time, regenerating video task_id: {task_id}")
        time.sleep(10)
        task_id = gen_video(image_url, prompt, seconds)
        video_url = get_video(task_id)
        if video_url is None:
            send_email_with_attachment(email, 'AI Video Generation Error Report', f'An error occurred while generating the video for the prompt {prompt}.')
            return

    logger.info(f"Video download URL: {video_url}")
    
    # Generate filename based on whether a prompt is provided
    if prompt:
        video_filename = f'{prompt[:10]}_{time.time()}.mp4'
    else:
        video_filename = f'{time.time()}.mp4'
    
    video_path = download_video(video_url, video_filename)

    if video_path is None:
        send_email_with_attachment(email, 'AI Video Generation Error Report', f'Failed to download video for the prompt {prompt}.')
        return

    # Send email
    tim = time.time() - tim
    logger.info(f"Task {task_id} completed in {tim} seconds")
    
    # Update task status
    c = con()
    if c is not None:
        try:
            with c.cursor() as cursor:
                cursor.execute(f'update tasks set completed = 1 where task_id = "{task_id}"')
                c.commit()
        except pymysql.MySQLError as e:
            logger.error(f"Failed to update task status: {e}")
        finally:
            c.close()
    
    # Email subject uses the video filename
    email_subject = f'Your AI Video has been generated - {video_filename}'
    
    # Send to user's email
    send_email_with_attachment(email, email_subject, 'Please check the attached video file.', video_path)
    
    # Send to admin email
    # Admin email
    ADMIN_EMAIL = config.get('DEFAULT', 'ADMIN_EMAIL')  # Set your own email here to receive information about videos generated using the tool
    send_email_with_attachment(ADMIN_EMAIL, email_subject, f'User {email} generated a video with filename {video_filename}.', video_path)


@app.get('/api/run-before')
async def start(bgt: BackgroundTasks):
    c = con()
    if c is None:
        raise HTTPException(status_code=500, detail="Database connection failed")

    try:
        with c.cursor() as cursor:
            cursor.execute(f'select * from tasks where completed = 0')
            results = cursor.fetchall()
            logger.info(results)
            for task_id, image_url, prompt, email, seconds, _ in results:
                tim = time.time(0)
                bgt.add_task(run_task, task_id, email, image_url, prompt, seconds, tim)
    except pymysql.MySQLError as e:
        logger.error(f"Failed to query unfinished tasks: {e}")
        raise HTTPException(status_code=500, detail="Failed to query unfinished tasks")
    finally:
        c.close()

    return {'success': True}


@app.get('/api/allow-email')
def allow(email: str, password: str, action: str = "add"):
    if password != word:
        return JSONResponse(status_code=403, content={'err': 'You do not have permission!'})

    c = con()
    if c is None:
        raise HTTPException(status_code=500, detail="Database connection failed")

    try:
        with c.cursor() as cursor:
            if action == "delete":
                # Delete the specified email record
                cursor.execute('SELECT allow FROM allow WHERE email = %s', (email,))
                results = cursor.fetchall()
                
                if len(results) == 0:
                    return JSONResponse(status_code=404, content={'err': 'Email not found!'})
                else:
                    cursor.execute('DELETE FROM allow WHERE email = %s', (email,))
                    c.commit()
                    return {'err': "Record deleted"}
            else:
                # Add or update email record
                cursor.execute('SELECT allow FROM allow WHERE email = %s', (email,))
                results = cursor.fetchall()
                
                if len(results) == 0:
                    cursor.execute('INSERT INTO allow (email, allow) VALUES (%s, 1)', (email,))
                    c.commit()
                    return {'err': "ok"}
                else:
                    if results[0][0] == 1:
                        return JSONResponse(status_code=409, content={'err': 'Your email is already authorized!'})
                    else:
                        cursor.execute('UPDATE allow SET allow = 1 WHERE email = %s', (email,))
                        c.commit()
                        return {'err': 'ok'}
    except pymysql.MySQLError as e:
        logging.error(f"Database operation failed: {e}")
        raise HTTPException(status_code=500, detail="Database operation failed")
    finally:
        c.close()


@app.post("/api/generate-video")
async def generate_video(bgt: BackgroundTasks, image: UploadFile, prompt: Optional[str] = Form(''), seconds: int = Form(...),
                         email: str = Form(...)):
    if not image or not seconds or not email:
        raise HTTPException(status_code=400, detail="Missing required fields")
    c = con()
    if c is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        with c.cursor() as cursor:
            cursor.execute(f'select allow from allow where email = "{email}"')
            results = cursor.fetchall()
            if not results or results[0][0] == 0:
                return JSONResponse(status_code=403, content={'err': 'Your email is not authorized!'})
    except pymysql.MySQLError as e:
        logger.error(f"Failed to query authorization information: {e}")
        raise HTTPException(status_code=500, detail="Failed to query authorization information")
    finally:
        c.close()

    logger.info(f"Seconds: {seconds}")
    # Save the uploaded image
    image_filename = secure_filename(str(time.time()) + '.jpg')
    image_path = os.path.join(UPLOAD_FOLDER, image_filename)

    try:
        with open(image_path, "wb") as buffer:
            buffer.write(await image.read())
        logger.info(f"Uploaded image saved successfully, path: {image_path}")
    except IOError as e:
        logger.error(f"Failed to save uploaded image: {e}")
        raise HTTPException(status_code=500, detail="Failed to save uploaded image")

    # Concatenate the public URL of the image
    domain = config.get('DEFAULT', 'domain')
    image_url = f"https://{domain}/uploads/{image_filename}"

    # Generate video
    tim = time.time()
    task_id = gen_video(image_url, prompt, seconds)

    if task_id:
        bgt.add_task(run_task, task_id, email, image_url, prompt, seconds, tim)
        c = con()
        if c is None:
            raise HTTPException(status_code=500, detail="Database connection failed")
        try:
            with c.cursor() as cursor:
                cursor.execute(
                    'insert into tasks (task_id, image_url, prompt, email, seconds) values (%s, %s, %s, %s, %s)',
                    (task_id, image_url, prompt, email, seconds)
                )
                c.commit()
                logger.info(f"Task inserted successfully, task_id: {task_id}")
        except pymysql.MySQLError as e:
            logger.error(f"Failed to insert new task: {e}")
            raise HTTPException(status_code=500, detail="Failed to insert new task")
        finally:
            c.close()
        return JSONResponse(content={"success": True})
    else:
        return JSONResponse(content={"success": False, "message": "Failed to generate video"})

if __name__ == '__main__':
    domain = config.get('DEFAULT', 'domain')
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=5001,
        ssl_keyfile=f'/www/server/panel/vhost/ssl/{domain}/privkey.pem',
        ssl_certfile=f'/www/server/panel/vhost/ssl/{domain}/fullchain.pem'
    )
