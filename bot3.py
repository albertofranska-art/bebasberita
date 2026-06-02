import os
import json
import time
import requests
import sys
import tempfile
import re

from urllib.parse import urljoin

from bs4 import BeautifulSoup
from gnews import GNews

# =========================
# SELENIUM
# =========================
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager

# =========================
# GEMINI
# =========================
import google.generativeai as genai

# =========================
# GLOBAL
# =========================
CONFIG = {}

LOG_FILE = "processed_topics.log"

GEMINI_KEYS_FILE = "gemini_keys.txt"

def load_gemini_keys():

    print(
        f"INFO: Membaca {GEMINI_KEYS_FILE}"
    )

    if not os.path.isfile(
        GEMINI_KEYS_FILE
    ):

        print(
            f"❌ File {GEMINI_KEYS_FILE} tidak ditemukan."
        )

        return []

    with open(
        GEMINI_KEYS_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        keys = [
            line.strip()
            for line in f.readlines()
            if line.strip()
        ]

    print(
        f"INFO: {len(keys)} Gemini API Key ditemukan."
    )

    return keys

# =========================
# CLEAN EMOJI BMP ERROR
# =========================
def clean_non_bmp(text):

    return ''.join(
        c for c in text
        if ord(c) <= 0xFFFF
    )

# =========================
# LOAD CONFIG
# =========================
def load_config():

    global CONFIG

    try:

        with open("config.json", "r", encoding="utf-8") as f:
            CONFIG = json.load(f)

        print("✅ Konfigurasi berhasil dimuat dari config.json.")

        return True

    except Exception as e:

        print(f"❌ KESALAHAN: Gagal memuat config.json: {e}")

        return False

# =========================
# LICENSE
# =========================
VALIDATION_SERVER_URL = "https://license-server-botnews.vercel.app/api/validate"

PRODUCT_NAME = "botsosmed"

def check_license():

    license_key = os.getenv("BOT_LICENSE_EMAIL")

    if not license_key:

        print("❌ BOT_LICENSE_EMAIL tidak ditemukan.")

        return False

    print(f"🔑 Memvalidasi lisensi untuk produk '{PRODUCT_NAME}'...")

    try:

        url = f"{VALIDATION_SERVER_URL}?email={license_key}&product={PRODUCT_NAME}"

        response = requests.get(url, timeout=15)

        if response.status_code == 200 and response.json().get("status") == "valid":

            print("✅ Lisensi valid.")

            return True

        else:

            print(f"❌ Lisensi tidak valid: {response.text}")

            return False

    except Exception as e:

        print(f"❌ Gagal menghubungi server lisensi: {e}")

        return False

# =========================
# PROCESSED TOPICS
# =========================
def get_processed_items():

    if not os.path.exists(LOG_FILE):
        return set()

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)

def add_item_to_log(item_id):

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{item_id}\n")

# =========================
# REDIRECT URL
# =========================
def get_real_url_via_selenium(google_news_url):

    print("INFO: [Redirect Selenium] Resolve URL asli...")

    chrome_options = Options()

    chrome_options.add_argument("--headless")

    chrome_options.add_argument("--no-sandbox")

    chrome_options.add_argument("--disable-dev-shm-usage")

    driver = None

    try:

        service = Service(
            ChromeDriverManager().install()
        )

        driver = webdriver.Chrome(
            service=service,
            options=chrome_options
        )

        driver.get(google_news_url)

        for _ in range(15):

            current_url = driver.current_url

            if "google.com" not in current_url:

                print(f"SUCCESS: URL asli ditemukan -> {current_url}")

                return current_url

            time.sleep(1)

        return None

    except Exception as e:

        print(f"ERROR: Redirect gagal -> {e}")

        return None

    finally:

        if driver:
            driver.quit()

# =========================
# AMBIL GAMBAR
# =========================
def get_image_from_article_url(article_url):

    if not article_url:
        return None

    print(f"INFO: [Gambar] Mencari gambar dari: {article_url}")

    try:

        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        response = requests.get(
            article_url,
            headers=headers,
            timeout=15,
            allow_redirects=True
        )

        response.raise_for_status()

        response.encoding = "utf-8"

        soup = BeautifulSoup(response.text, "html.parser")

        og_image = soup.find(
            "meta",
            property="og:image"
        )

        if og_image and og_image.get("content"):

            img_link = urljoin(
                article_url,
                og_image["content"]
            )

            if img_link.startswith("http"):

                print("SUCCESS: Gambar ditemukan.")

                return img_link

        return None

    except Exception as e:

        print(f"ERROR: Gagal mengambil gambar: {e}")

        return None

# =========================
# GNEWS
# =========================
def get_context_and_image_from_gnews(topic):

    print(f"INFO: [GNews] Mencari berita untuk '{topic}'...")

    try:

        gnews_client = GNews(
            language=CONFIG["GNEWS_CONFIG"]["language"],
            country=CONFIG["GNEWS_CONFIG"]["country"],
            max_results=1
        )

        articles = gnews_client.get_news(topic)

        if not articles:

            return {
                "context": f"Tidak ada berita untuk '{topic}'.",
                "image_url": None
            }

        top_article = articles[0]

        news_context = (
			f"Judul berita: {top_article['title']}\n"
			f"Deskripsi: {top_article['description']}\n"
			f"Sumber: {top_article['publisher']['title']}"
		)

        real_article_url = get_real_url_via_selenium(
            top_article["url"]
        )

        image_url = get_image_from_article_url(
            real_article_url
        )

        return {
            "context": news_context,
            "image_url": image_url
        }

    except Exception as e:

        print(f"ERROR: GNews gagal -> {e}")

        return {
            "context": f"Gagal riset untuk {topic}",
            "image_url": None
        }

# =========================
# GOOGLE TRENDS
# =========================
def scrape_google_trends():

    config = CONFIG["GOOGLE_TRENDS_CONFIG"]

    params = f"geo={config.get('geo', 'ID')}&hl={config.get('hl', 'id')}"

    if config.get("hours"):
        params += f"&hours={config['hours']}"

    if config.get("category"):
        params += f"&category={config['category']}"

    target_url = f"https://trends.google.com/trending?{params}"

    print(f"INFO: [Google Trends] Membuka URL: {target_url}")

    chrome_options = Options()

    chrome_options.add_argument("--headless")

    chrome_options.add_argument("--no-sandbox")

    chrome_options.add_argument("--disable-dev-shm-usage")

    driver = None

    try:

        service = Service(
            ChromeDriverManager().install()
        )

        driver = webdriver.Chrome(
            service=service,
            options=chrome_options
        )

        driver.get(target_url)

        wait = WebDriverWait(driver, 30)

        wait.until(
            EC.presence_of_element_located(
                (By.TAG_NAME, "body")
            )
        )

        print("SUCCESS: Halaman Google Trends dimuat.")

        # =========================
        # AUTO SCROLL
        # =========================
        last_height = driver.execute_script(
            "return document.body.scrollHeight"
        )

        for _ in range(10):

            driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )

            time.sleep(3)

            new_height = driver.execute_script(
                "return document.body.scrollHeight"
            )

            if new_height == last_height:
                break

            last_height = new_height

        print("SUCCESS: Auto scroll selesai.")

        rows = driver.find_elements(By.TAG_NAME, "tr")

        processed_items = get_processed_items()

        for row in rows:

            try:

                elements = row.find_elements(
                    By.CSS_SELECTOR,
                    "div.mZ3RIc"
                )

                if not elements:
                    continue

                keyword = elements[0].text.strip()

                if not keyword:
                    continue

                unique_id = f"gt_{keyword}"

                # =========================
                # SKIP DUPLIKAT
                # =========================
                if unique_id in processed_items:

                    print(f"INFO: Skip duplicate -> {keyword}")

                    continue

                print(f"SUCCESS: Keyword baru -> {keyword}")

                return {
                    "id": unique_id,
                    "title": keyword
                }

            except Exception:
                continue

        print("INFO: Tidak ada topic baru.")

        return None

    except Exception as e:

        print(f"ERROR: Google Trends gagal -> {e}")

        return None

    finally:

        if driver:
            driver.quit()

# =========================
# HASHTAG
# =========================
def get_trends24_hashtags():

    config = CONFIG.get("TRENDS24_CONFIG")

    if not config or not config.get("scrape_url"):
        return []

    print("INFO: Mengambil hashtag trends...")

    try:

        response = requests.get(
            config["scrape_url"],
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20
        )

        response.raise_for_status()

        response.encoding = "utf-8"

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        trends = [
            link.get_text(strip=True)
            for link in soup.find(
                "ol",
                class_="trend-card__list"
            ).find_all("a")
        ]

        return trends[:config.get("trending_limit", 0)]

    except Exception as e:

        print(f"WARNING: Gagal mengambil hashtag: {e}")

        return []

# =========================
# GEMINI GENERATE
# =========================

def generate_tweet_text(
    topic,
    news_context
):

    print(
        "INFO: [Gemini] Membuat teks tweet..."
    )

    api_keys = load_gemini_keys()

    if not api_keys:

        print(
            "❌ Tidak ada Gemini API Key."
        )

        return None

    prompt = CONFIG[
        "GEMINI_PROMPTS"
    ]["generate_tweet"].format(
        topic=topic,
        news_context=news_context
    )

    for index, api_key in enumerate(api_keys):

        try:

            print(
                f"INFO: Mencoba Gemini Key #{index + 1}"
            )

            genai.configure(
                api_key=api_key
            )

            model = genai.GenerativeModel(
                CONFIG[
                    "GEMINI_SETTINGS"
                ]["model"]
            )

            response = model.generate_content(
                prompt
            )

            text = response.text.strip()

            text = clean_non_bmp(
                text
            )

            print(
                f"SUCCESS: Gemini Key #{index + 1} berhasil."
            )

            return text

        except Exception as e:

            print(
                f"WARNING: Gemini Key #{index + 1} gagal -> {e}"
            )

            continue

    print(
        "❌ Semua Gemini API Key gagal."
    )

    return None

# =========================
# TWITTER SELENIUM
# =========================
def post_to_twitter(tweet_text, image_url, all_hashtags, traffic_link):

    print("INFO: Memulai proses posting X...")

    MAX_TWEET_LENGTH = 25000

    main_content = tweet_text

    if traffic_link:
        main_content = f"{tweet_text}\n\n{traffic_link}"

    hashtag_part = ""

    available_space = MAX_TWEET_LENGTH - (
        len(main_content) + 2
    )

    unique_tags = []

    for tag in all_hashtags:

        tag = clean_non_bmp(tag.strip())

        if not tag:
            continue

        if len(hashtag_part) + len(tag) + 1 <= available_space:

            if tag not in unique_tags:

                hashtag_part += f" {tag}"

                unique_tags.append(tag)

        else:

            print(f"WARNING: Hashtag '{tag}' dilewati.")

            break

    hashtag_part = hashtag_part.strip()

    final_tweet_text = f"{main_content}\n\n{hashtag_part}"

    # CLEAN FINAL TEXT
    final_tweet_text = clean_non_bmp(
        final_tweet_text
    )

    chrome_options = Options()

    chrome_options.add_argument("--headless=new")

    chrome_options.add_argument("--no-sandbox")

    chrome_options.add_argument("--disable-dev-shm-usage")

    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    chrome_options.add_argument("--disable-infobars")

    chrome_options.add_argument("--window-size=1920,1080")

    chrome_options.add_experimental_option(
        "excludeSwitches",
        ["enable-automation"]
    )

    chrome_options.add_experimental_option(
        "useAutomationExtension",
        False
    )

    driver = None

    try:

        service = Service(
            ChromeDriverManager().install()
        )

        driver = webdriver.Chrome(
            service=service,
            options=chrome_options
        )

        driver.execute_script("""
        Object.defineProperty(
            navigator,
            'webdriver',
            {get: () => undefined}
        )
        """)

        print("INFO: Membuka X...")

        driver.get("https://x.com")

        time.sleep(5)

        auth_token = os.getenv(
            "TWITTER_AUTH_TOKEN"
        )

        ct0 = os.getenv(
            "TWITTER_CT0"
        )

        if not auth_token or not ct0:

            print("❌ Secret X tidak ditemukan.")

            return False

        # =========================
        # COOKIE LOGIN
        # =========================
        driver.add_cookie({
            "name": "auth_token",
            "value": auth_token,
            "domain": ".x.com",
            "path": "/"
        })

        driver.add_cookie({
            "name": "ct0",
            "value": ct0,
            "domain": ".x.com",
            "path": "/"
        })

        print("INFO: Session injected.")

        driver.refresh()

        time.sleep(8)

        driver.get(
            "https://x.com/compose/post"
        )

        print("INFO: Membuka compose tweet...")

        time.sleep(8)

        wait = WebDriverWait(driver, 30)

        # =========================
        # TEXTBOX
        # =========================
        tweet_box = wait.until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    'div.DraftEditor-editorContainer div[contenteditable="true"]'
                )
            )
        )

        driver.execute_script("""
        arguments[0].scrollIntoView(true);
        """, tweet_box)

        time.sleep(2)

        driver.execute_script("""
        arguments[0].focus();
        """, tweet_box)

        time.sleep(1)

        driver.execute_script("""
        arguments[0].click();
        """, tweet_box)

        time.sleep(1)

        # =========================
        # INPUT TEXT
        # =========================
        tweet_box.send_keys(final_tweet_text)

        time.sleep(3)

        print(f"INFO: Caption -> {final_tweet_text}")

        # =========================
        # UPLOAD GAMBAR
        # =========================
        if image_url:

            try:

                print(f"INFO: Download gambar -> {image_url}")

                response = requests.get(
                    image_url,
                    stream=True,
                    timeout=20
                )

                response.raise_for_status()

                with tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=".jpg"
                ) as tmp_file:

                    for chunk in response.iter_content(
                        chunk_size=8192
                    ):
                        tmp_file.write(chunk)

                    tmp_path = tmp_file.name

                file_input = wait.until(
                    EC.presence_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            'input[type="file"]'
                        )
                    )
                )

                file_input.send_keys(tmp_path)

                print("INFO: Upload media...")

                time.sleep(10)

                os.unlink(tmp_path)

                print("SUCCESS: Media berhasil diupload.")

            except Exception as media_error:

                print(f"WARNING: Upload media gagal -> {media_error}")

        # =========================
        # POST BUTTON
        # =========================
        post_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.CSS_SELECTOR,
                    'button[data-testid="tweetButton"]'
                )
            )
        )

        driver.execute_script("""
        arguments[0].scrollIntoView(true);
        """, post_button)

        time.sleep(2)

        driver.execute_script("""
        arguments[0].click();
        """, post_button)

        print("INFO: Tweet dipublikasikan...")

        time.sleep(10)

        print("🎉 Tweet berhasil dipublikasikan!")

        return True

    except Exception as e:

        print(f"❌ Gagal posting tweet: {e}")

        return False

    finally:

        if driver:
            driver.quit()

# =========================
# MAIN
# =========================
def main():

    if not check_license():
        sys.exit(1)

    if not load_config():
        sys.exit("Eksekusi dihentikan.")

    print("\n--- Memulai Eksekusi Bot ---")

    topic_data = scrape_google_trends()

    if not topic_data:

        print("INFO: Tidak ada topic baru.")

        return

    research_data = get_context_and_image_from_gnews(
        topic_data["title"]
    )

    tweet_text = generate_tweet_text(
        topic_data["title"],
        research_data["context"]
    )

    if tweet_text:

        traffic_link = CONFIG.get(
            "TWITTER_CONFIG",
            {}
        ).get(
            "traffic_link",
            ""
        )

        scraped_hashtags = get_trends24_hashtags()

        manual_hashtags = CONFIG.get(
            "TWITTER_CONFIG",
            {}
        ).get(
            "manual_hashtags",
            []
        )

        main_topic_hashtag = "#" + topic_data["title"].replace(" ", "")

        all_hashtags = (
            [main_topic_hashtag]
            + scraped_hashtags
            + manual_hashtags
        )

        if post_to_twitter(
            tweet_text,
            research_data.get("image_url"),
            all_hashtags,
            traffic_link
        ):

            add_item_to_log(
                topic_data["id"]
            )

    print("--- Eksekusi Bot Selesai ---")

if __name__ == "__main__":
    main()
