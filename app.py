from flask import Flask, request, jsonify
import requests
import sqlite3
import os
import asyncio
import random
import threading
import time
from dotenv import load_dotenv
from datetime import datetime
from twikit import Client
from openai import OpenAI

# === Load Environment Variables ===
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

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
        analyzed_at TEXT,
        raw_tweets TEXT,
        analysis TEXT
    )
""")
conn.commit()

# === Scrape Tweets from Twitter via Twikit ===
async def get_latest_tweets(client, username, limit=15):
    try:
        user = await client.get_user_by_screen_name(username)
        tweets = await user.get_tweets(tweet_type="Tweets", count=limit)
        return [t.full_text for t in tweets if len(t.full_text.strip()) > 20]
    except Exception as e:
        print(f"❌ Twikit error during tweet fetch: {e}")
        return []

# === Estimate Token Usage ===
def estimate_token_count(tweets):
    return len(tweets) * 25

# === Analyze with OpenAI and Enforce Short Tweet ===
def analyze_user(username, tweets, metadata, max_len=260):
    token_estimate = estimate_token_count(tweets)
    if token_estimate > 2000:
        return "⚠️ Token limit exceeded."

    client = OpenAI(api_key=OPENAI_API_KEY)

    system_prompt = (
        "You are Truth kwa Masses, a concise AI analyst exposing coordinated state-aligned Twitter activity in Kenya.\n"
        "Analyze patterns of inorganic messaging, influencer loops, repeated hashtags.\n"
        "Generate a single tweet in Telegram-style. Start with outcome, use emoji to indicate confidence:\n"
        "🟢 Organic\n🟠 Unclear\n🔴 Coordinated\n"
        "Make it short, punchy, and under 260 characters."
    )

    base_prompt = f"""Analyze this user:

Username: @{username}
Joined: {metadata.get('joined')}
Followers: {metadata.get('followers')}

Here are their last {len(tweets)} tweets:
{chr(10).join(f"{i+1}. {t}" for i, t in enumerate(tweets))}
"""

    print("🧠 Sending to OpenAI...")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": base_prompt}
    ]

    for attempt in range(3):
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        summary = response.choices[0].message.content.strip()

        if len(summary) <= max_len:
            return summary

        print(f"⚠️ Too long ({len(summary)} chars), retrying...")
        messages.append({
            "role": "user",
            "content": "That was too long. Rephrase the same message under 240 characters. Make it even more concise and impactful."
        })

    return summary[:max_len - 1] + "…"

# === Monitor Mentions of @truthkwaMasses ===
def poll_mentions():
    async def _check_mentions():
        client = Client(language="en-US")
        await client.login(
            auth_info_1=os.getenv("TWITTER_USERNAME"),
            auth_info_2=os.getenv("TWITTER_EMAIL"),
            password=os.getenv("TWITTER_PASSWORD"),
            cookies_file="cookies.json"
        )
        tweets = await client.search_tweet("@truthkwaMasses", "Latest")
        for tweet in tweets:
            tweet_id = tweet.id
            mentioner = tweet.user.screen_name
            text = tweet.text

            print(f"🔍 Mention by @{mentioner}: {text}")

            c.execute("SELECT 1 FROM processed_tweets WHERE tweet_id = ?", (tweet_id,))
            if c.fetchone():
                print("⏭️ Already processed this mention.")
                continue

            words = text.split()
            target = next((w[1:] for w in words if w.startswith("@") and w.lower() != "@truthkwamasses"), None)
            if not target:
                print("⚠️ No target username found.")
                continue

            print(f"🎯 Target user to analyze: @{target}")

            tweets_to_analyze = await get_latest_tweets(client, target)
            if not tweets_to_analyze:
                print("❌ No tweets to analyze.")
                continue

            metadata = {"joined": "unknown", "followers": 0}
            summary = analyze_user(target, tweets_to_analyze, metadata)

            reply_text = f"@{mentioner} {summary}"
            if len(reply_text) > 279:
                reply_text = reply_text[:278] + "…"
            print(f"💬 Replying with: {reply_text}")

            try:
                await tweet.reply(text=reply_text)
                print("✅ Replied successfully.")
            except Exception as e:
                print(f"❌ Error replying: {e}")
                continue

            c.execute("INSERT INTO processed_tweets VALUES (?, ?, ?, ?, ?)", (
                tweet_id,
                target,
                datetime.utcnow().isoformat(),
                "\n".join(tweets_to_analyze),
                summary
            ))
            conn.commit()
            print("📝 Logged mention.")

    while True:
        try:
            asyncio.run(_check_mentions())
        except Exception as e:
            print(f"⚠️ Polling error: {e}")
        delay = random.randint(70, 130)
        print(f"🕒 Sleeping {delay}s before next poll...")
        time.sleep(delay)

mention_thread = threading.Thread(target=poll_mentions, daemon=True)
mention_thread.start()

@app.route("/", methods=["GET"])
def index():
    return "✅ Ukwelify is live!", 200

@app.route("/healthz", methods=["GET"])
def health_check():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    tweet_id = data.get("tweet_id")
    username = data.get("target_username")
    metadata = {
        "joined": data.get("joined", "unknown"),
        "followers": data.get("followers", 0)
    }

    print("🔁 Incoming request from:", username)
    print("🔍 Checking dedupe...")
    c.execute("SELECT 1 FROM processed_tweets WHERE tweet_id = ?", (tweet_id,))
    if c.fetchone():
        print("⏭️ Already processed")
        return jsonify({"status": "already_processed"}), 200

    print("🗕️ Scraping tweets...")
    tweets = asyncio.run(get_latest_tweets(Client(language="en-US"), username))
    if not tweets:
        print("❌ No tweets found")
        return jsonify({"status": "no_tweets"}), 400

    print("🧠 Analyzing tweets...")
    thread = analyze_user(username, tweets, metadata)
    if thread.startswith("⚠️"):
        print("⚠️ Skipped due to token limit")
        return jsonify({"status": "skipped", "reason": thread}), 400

    print("✅ Logging to DB and returning response")
    c.execute("INSERT INTO processed_tweets VALUES (?, ?, ?, ?, ?)",
              (tweet_id, username, datetime.utcnow().isoformat(), "\n".join(tweets), thread))
    conn.commit()

    return jsonify({"status": "posted", "reply": thread})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
