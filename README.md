# OptiBot Clone

AI-powered support bot that scrapes OptiSigns documentation and answers questions using OpenAI Assistants.

## Setup

```bash
git clone <repo-url>
cd optibot-clone
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:
```
OPENAI_API_KEY=...
```

## Run Locally

```bash
# Full pipeline: scrape ALL articles + upload delta
python main.py cron

# Scrape only
python main.py scrape --all                    # all articles
python main.py scrape --limit 30               # 30 articles
python main.py scrape --priority youtube        # prioritize youtube articles
python main.py scrape --limit 30 --priority youtube,google  # combined

# Upload existing files to vector store
python main.py upload

# Full pipeline with limit
python main.py full --limit 50

# Start web server (with built-in scheduler)
python main.py
```

## Create Assistant

1. Go to [OpenAI Platform](https://platform.openai.com)
2. Create Assistant → Add Vector Store
3. Upload files from `articles/` folder
4. Set System Prompt:

```
You are OptiBot, OptiSigns customer-support bot.

**Rules:**
- Answer ONLY from uploaded docs
- Cite steps with "Article URL:" at end
- Keep answers concise (≤5 bullets)
- If info not in docs, say so

**Answer format:**
[Brief answer]

Article URL: [exact URL]
```

## Daily Job

## Sample Q&A
