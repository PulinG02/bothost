# 🤖 BotHost — Python & Telegram Bot Hosting

I-host ang iyong mga Python Telegram bots sa cloud gamit ang simpleng dashboard.

---

## 🚀 I-deploy sa Railway (Libre)

### Step 1 — Gumawa ng GitHub account
Kung wala ka pa: https://github.com/signup

### Step 2 — I-upload ang project sa GitHub
1. Pumunta sa https://github.com/new
2. Pangalanan ang repo: `bothost`
3. I-click ang **"uploading an existing file"**
4. I-drag ang lahat ng files mula sa folder na ito
5. I-click ang **"Commit changes"**

### Step 3 — I-deploy sa Railway
1. Pumunta sa https://railway.app
2. I-click ang **"Start a New Project"**
3. Piliin ang **"Deploy from GitHub repo"**
4. Piliin ang iyong `bothost` repo
5. Railway auto-detects ang Python at mag-de-deploy agad
6. Hintayin ang build (~1-2 minuto)
7. I-click ang **"Generate Domain"** para makuha ang public URL

✅ Tapos! Buksan ang URL — nandoon na ang dashboard.

---

## 🎨 I-deploy sa Render (Alternative)

1. Pumunta sa https://render.com
2. I-click ang **"New Web Service"**
3. I-connect ang GitHub repo
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `python server.py`
6. I-click ang **"Create Web Service"**

---

## 📱 Paano Gumamit ng Dashboard

### Para mag-deploy ng bot:
1. Buksan ang dashboard URL
2. I-click ang **➕ Deploy Bot**
3. I-type ang pangalan ng bot
4. I-paste ang Telegram Bot Token
5. I-upload ang `.py` file ng iyong bot
6. I-click ang **🚀 Deploy Bot**

### Para gumawa ng Telegram Bot Token:
1. Buksan ang Telegram app
2. Hanapin ang **@BotFather**
3. I-type: `/newbot`
4. Sundin ang steps → makakakuha ng token na ganito:
   `1234567890:AAExampleTokenXXXXXXXXXXXXXXXXXXXXX`

---

## 📦 Mga Files

```
bothost/
├── server.py          # FastAPI backend (ang nagre-run ng mga bot)
├── requirements.txt   # Python dependencies
├── Procfile           # Para sa Railway
├── render.yaml        # Para sa Render
├── runtime.txt        # Python version
├── nixpacks.toml      # Railway build config
├── example_bot.py     # Sample bot para i-test
└── templates/
    └── index.html     # Dashboard frontend
```

---

## ⚠️ Importante

- Ang bots ay **talagang nag-eexecute** ng Python code sa server
- Ang BOT_TOKEN ay nire-receive ng bot via `os.environ.get("BOT_TOKEN")`
- Kung kailangan ng bot mo ng extra libraries (e.g. `requests`, `pyTelegramBotAPI`), dagdag mo sa `requirements.txt`
- Sa Railway/Render free tier: ang server ay natutulog pagkatapos ng inactivity — gamitin ang paid tier para 24/7

---

## 🔧 Kung Kailangan ng Extra Python Libraries

I-edit ang `requirements.txt` bago mag-deploy:

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
python-multipart==0.0.9
pyTelegramBotAPI==4.19.0    # Para sa Telegram bots
requests==2.31.0             # Para sa HTTP requests
python-dotenv==1.0.0         # Para sa .env files
```
