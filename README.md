# Ukwelify

**Ukwelify** is an automated truth analyzer for Twitter/X. It scans replies and mentions to `@ukwelify`, scrapes the target account’s recent activity, and uses OpenAI to generate an insightful thread about the user's behavior, tone, and patterns.

> *"Ukweli" means "truth" in Swahili — Ukwelify reveals it.*

---

### 🔍 What It Does

- Monitors mentions of `@ukwelify` for commands like `@analyze`
- Scrapes target accounts using Nitter
- Analyzes tweet history using OpenAI (GPT-4o)
- Posts a response thread via Typefully
- Avoids duplication using a lightweight SQLite log

---

### 🛠 Stack

- **Python + Flask** – Webhook + API
- **SQLite** – Deduplication store
- **OpenAI** – Natural language analysis
- **Typefully API** – Posts threads as drafts to Twitter/X
- **Nitter** – Public tweet scraping layer

---

### 🚀 Quick Start

```bash
git clone https://github.com/yourname/ukwelify.git
cd ukwelify
pip install -r requirements.txt
cp .env.example .env  # Add your API keys
flask run
