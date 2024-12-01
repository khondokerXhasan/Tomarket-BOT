import os
import re
import json
import jsbeautifier
import cloudscraper
from datetime import datetime
from requests.exceptions import Timeout, ConnectionError, SSLError, HTTPError, RequestException
from aiocache import Cache, cached
from bot.utils import logger
from bot.config import settings

session = cloudscraper.create_scraper()
session.headers.update({
  'User-Agent': "Mozilla/5.0 (Linux; Android 9; Samsung SM-G892A) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.156 Mobile Safari/537.36 Telegram-Android/11.3.4 (Samsung SM-G892A; Android 9; SDK 28; AVERAGE)",
  'Accept': "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
  'Accept-Encoding': "utf-8",
  'sec-ch-ua': "\"Android WebView\";v=\"131\", \"Chromium\";v=\"131\", \"Not_A Brand\";v=\"24\"",
  'sec-ch-ua-mobile': "?1",
  'sec-ch-ua-platform': "\"Android\"",
  'upgrade-insecure-requests': "1",
  'x-requested-with': "org.telegram.messenger",
  'sec-fetch-site': "none",
  'sec-fetch-mode': "navigate",
  'sec-fetch-user': "?1",
  'sec-fetch-dest': "document",
  'accept-language': "en,en-US;q=0.9,bn-BD;q=0.8,bn;q=0.7",
  'priority': "u=0, i",
})
#URL's
BASE_PAGE_URL = "https://mini-app.tomarket.ai/"
DETECTION_CONFIG_URL = "https://raw.githubusercontent.com/khondokerXhasan/bin/refs/heads/main/detect.json"
BASE_API = "https://api-web.tomarket.ai/tomarket-game/v1"

async def fetch_js_paths(base_url):
    try:
        response = session.get(base_url)
        response.raise_for_status()
        pattern = r'"(/assets/[^"]+\.js)"'
        matches = re.findall(pattern, response.text)
        return matches
    except Exception as e:
        logger.error(f"Error fetching JavaScript paths: {e}")
        return 

async def get_base_api(url):
    try:
        logger.info("Checking for changes in api...")
        response = session.get(url)
        response.raise_for_status()
        content = response.text
        pattern = r'online:"(https?://[^"]+)"'
        match = re.search(pattern, content)

        if match:
            return match.group(1)
        else:
            logger.warning("Could not find 'BASE_API' in the content.")
            return None
    except Exception as e:
        logger.error(f"Error fetching the JS file: {e}")
        return None

async def check_base_url(session_name):
    
    if settings.ADVANCED_ANTI_DETECTION:  
        logger.info(f"{session_name} | 🕵️‍♂️ Processing advanced detection...")
        return await advance_detection(BASE_PAGE_URL, DETECTION_CONFIG_URL)
    else:
        main_js_formats = await fetch_js_paths(BASE_PAGE_URL)
        if main_js_formats:
            for format_ in main_js_formats:
                logger.info(f"{session_name} | Trying format: <g>{format_}</g>")
                full_url = f"{BASE_PAGE_URL.rstrip('/')}{format_}"
                result = await get_base_api(full_url)
                if str(result) == BASE_API:
                    logger.info(f"{session_name} | No change in api!")
                    return True
            return False
                 
        else:
            logger.warning("Could not find any main.js format. Dumping page content for inspection:")
            try:
                response = session.get(base_url)
                print(response.text[:1000])
                return False
            except Exception as e:
                logger.error(f"Error fetching the base URL for content dump: {e}")
                return False      

@cached(ttl=2700, cache=Cache.MEMORY) # Cache detect.json file for 45 minutes
async def load_detection_data(
    config_url: str,
    max_retries: int = 5,
    delay: int = 3
) -> list:
    retries = 0
    while retries < max_retries:
        try:
            response = session.get(config_url, headers = {
                'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36",
                'Accept': "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            })
            response.raise_for_status()
            detection_data = response.json()["tomarket"]["index"]
            return [(item.split("|")[0], datetime.strptime(item.split("|")[1], '%Y-%m-%d %H:%M:%S')) for item in detection_data]
        except (Timeout, ConnectionError, SSLError, HTTPError, RequestException) as e:
            retries += 1
            logger.warning(f"Server error for {config_url}: {e}. Retrying ({retries}/{max_retries})")
            if retries < max_retries:
                await asyncio.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                logger.error(f"{self.session_name} | Max retries reached. DNS resolution error: {e}")
                raise  # Raise after max retries
        except Exception as e:
            logger.error(f"Error loading detection data: {e}")
            return []

async def get_js_file_last_modified(url):
    try:
        response = session.head(url)
        response.raise_for_status()
        last_modified = response.headers.get('Last-Modified')
        return datetime.strptime(last_modified, '%a, %d %b %Y %H:%M:%S %Z') if last_modified else None
    except Exception as e:
        logger.error(f"Error fetching Last-Modified header for {url}: {e}")
        return None

async def advance_detection(base_url, config_url):
    js_paths = await fetch_js_paths(base_url)
    if not js_paths:
        logger.warning("No JavaScript files found.")
        return False
        
    if settings.SAVE_JS_FILES:
        await save_js_files(js_paths)
    
    expected_files = await load_detection_data(config_url)
    if not expected_files:
        logger.warning("No expected JavaScript file data available.")
        return False

    for file_name, expected_time in expected_files:
        matching_path = next((path for path in js_paths if file_name in path), None)
        if not matching_path:
            logger.warning(f"Expected file <y>{file_name}</y> not found in JavaScript paths.")
            logger.info(f"JavaScript file Changed. New files: <e>{js_paths}</e>")
            return False
        
        full_url = f"{base_url.rstrip('/')}{matching_path}"
        actual_time = await get_js_file_last_modified(full_url)

        if actual_time != expected_time:
            logger.warning(f"Mismatch for file <y>{file_name}</y>: expected <e>{expected_time}</e>, got <e>{actual_time}</e>")
            return False

    logger.info("<g>🛡️ Bot is safe to run</g> ✅")
    return True


async def format_last_modified_date(last_modified_header):
    if last_modified_header:
        try:
            last_modified_date = datetime.strptime(last_modified_header, '%a, %d %b %Y %H:%M:%S %Z')
            return last_modified_date.strftime('%Y-%m-%d_%H-%M-%S')
        except ValueError:
            logger.warning("Could not parse Last-Modified header")
    return None

async def beautify_js(content):
    opts = jsbeautifier.default_options()
    opts.indent_size = 2
    return jsbeautifier.beautify(content, opts)

async def download_file(url, save_dir):
    filename = url.split("/")[-1]
    base_filename, extension = os.path.splitext(filename)
    
    response = session.get(url)
    if response.status_code != 200:
        logger.warning(f"Failed to download {url}, status code: {response.status_code}")
        return
    
    last_modified_header = response.headers.get('Last-Modified')
    last_modified_date = await format_last_modified_date(last_modified_header)
    
    if last_modified_date:
        filename = f"{base_filename}_{last_modified_date}{extension}"
    
    save_path = os.path.join(save_dir, filename)
    
    if os.path.exists(save_path):
        pass
    else:
        beautified_content = await beautify_js(response.text)
        with open(save_path, "w") as f:
            f.write(beautified_content)
        logger.info(f"📦 Saved <g>{url}</g> as <e>{save_path}</e>")

async def clean_up_old_files(directory, max_files=20):
    js_files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(".js")]
    
    if len(js_files) > max_files:
        js_files.sort(key=os.path.getmtime)
        
        files_to_delete = js_files[:-max_files]
        for file_path in files_to_delete:
            os.remove(file_path)
            logger.info(f"<m>Deleted old file: </m><y>{file_path}</y>")


async def save_js_files(js_paths):
    save_directory = "downloaded_js_files"
    
    os.makedirs(save_directory, exist_ok=True)
    
    for js_path in js_paths:
        full_url = f"{BASE_PAGE_URL.rstrip('/')}{js_path}"
        await download_file(full_url, save_directory)

    await clean_up_old_files(save_directory, max_files=10)