from flask import Flask, request, jsonify
import requests
import sqlite3
import openai
import os
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from datetime import datetime

# === Load Environment Variables ===
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TYPEFULLY_API_KEY = os.getenv("TYPEFULLY_API_KEY")

# === Setup Flask ===
app = Flask(__name__)

# === Setup SQLite ===
DB_PATH = "dedupe.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
c = conn.cursor()
c.execute("""
    CREATE TABLE IF NOT EXISTS processed_tweets (
        tweet_id TEXT PRIMARY KEY,
        username TEXT,
        analyzed_at TEXT
    )
""")
conn.commit()

# === Scrape Tweets from Nitter ===
def get_latest_tweets(username, limit=15):
    url = f"https://nitter.net/{username}"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    tweet_divs = soup.select('div.timeline-item .tweet-content')
    raw_tweets = [div.text.strip() for div in tweet_divs]
    tweets = [t for t in raw_tweets if len(t) > 20][:limit]
    return tweets

# === Estimate Token Usage ===
def estimate_token_count(tweets):
    return len(tweets) * 25

# === Analyze with OpenAI ===
def analyze_user(username, tweets, metadata):
    token_estimate = estimate_token_count(tweets)
    if token_estimate > 2000:
        return "⚠️ Token limit exceeded."

    openai.api_key = OPENAI_API_KEY
    system_prompt = (
        "You are FichuaBot, a savvy bot that detects suspicious Twitter behavior.\n"
        "You reply in a casual, smart, 1–5 tweet thread format."
    )
    user_prompt = f"""Analyze this user:

Username: @{username}
Joined: {metadata.get('joined')}
Followers: {metadata.get('followers')}

Here are their last {len(tweets)} tweets:
{chr(10).join(f"{i+1}. {t}" for i, t in enumerate(tweets))}

Generate a Twitter thread assessing their behavior.
"""

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )

    return response['choices'][0]['message']['content']

# === Post to Typefully ===
def post_to_typefully(thread_text):
    url = "https://api.typefully.com/v1/drafts/"
    headers = {"X-API-KEY": f"Bearer {TYPEFULLY_API_KEY}"}
    payload = {
        "content": thread_text,
        "threadify": True,
        "share": True
    }
    response = requests.post(url, json=payload, headers=headers)
    return response.json()

# === Main Webhook Route ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    tweet_id = data.get("tweet_id")
    username = data.get("target_username")
    metadata = {
        "joined": data.get("joined", "unknown"),
        "followers": data.get("followers", 0)
    }

    c.execute("SELECT 1 FROM processed_tweets WHERE tweet_id = ?", (tweet_id,))
    if c.fetchone():
        return jsonify({"status": "already_processed"}), 200

    tweets = get_latest_tweets(username)
    if not tweets:
        return jsonify({"status": "no_tweets"}), 400

    thread = analyze_user(username, tweets, metadata)
    if thread.startswith("⚠️"):
        return jsonify({"status": "skipped", "reason": thread}), 400

    result = post_to_typefully(thread)

    c.execute("INSERT INTO processed_tweets VALUES (?, ?, ?)",
              (tweet_id, username, datetime.utcnow().isoformat()))
    conn.commit()

    return jsonify({"status": "posted", "share_url": result.get("share_url")})

# === Run Flask ===
if __name__ == "__main__":
    app.run(debug=True, port=5000)
