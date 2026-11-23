import os
from groq import Groq

api_key = os.environ.get("GROQ_API_KEY")
if not api_key:
    raise RuntimeError("找不到環境變數 GROQ_API_KEY")

client = Groq(api_key=api_key)
logs = []


def log(msg: str):
    print(msg)
    logs.append(msg)


def pick_working_chat_model() -> str:
    models = client.models.list().data
    candidates = [m.id for m in models if getattr(m, "id", None)]

    # 排除語音、TTS、ASR、Guard 與上下文較小的 7b/8b/9b 類模型
    skip_keywords = (
        "whisper",
        "orpheus",
        "guard",
        "safeguard",
        "prompt-guard",
        "tts",
        "allam",
    )
    filtered = [m for m in candidates if not any(k in m.lower() for k in skip_keywords)]

    preferred = [
        "llama-3.3-70b-versatile",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
        "qwen/qwen3-32b",
        "moonshotai/kimi-k2-instruct",
        "llama-3.1-8b-instant",
        "gemma2-9b-it",
    ]

    ordered = [m for m in preferred if m in filtered] + [m for m in filtered if m not in preferred]

    for model_id in ordered:
        try:
            client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
                temperature=0,
            )
            return model_id
        except Exception as e:
            log(f"[Model Probe] 跳過 {model_id}: {e}")

    raise RuntimeError("找不到任何可直接呼叫的 Groq 文字模型")


ACTIVE_MODEL = pick_working_chat_model()
log(f"[Init] 已選定可用模型: {ACTIVE_MODEL}")


def ask_llm(prompt: str, model: str = ACTIVE_MODEL, temp: float = 0.3) -> str:
    current_prompt = prompt
    for _ in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": current_prompt}],
                temperature=temp,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            err_msg = str(e).lower()
            if "reduce the length" in err_msg or "too large" in err_msg or "tokens" in err_msg:
                # 若超過上下文長度，將 prompt 縮減為 60% 後重試
                cut_len = max(1500, int(len(current_prompt) * 0.6))
                log(f"[Length Guard] 訊息過長，自動縮減至 {cut_len} 字元後重試...")
                current_prompt = current_prompt[:cut_len] + "\n\n[內容已截斷以符合長度限制]"
            else:
                raise
    raise RuntimeError("多次縮減長度後仍無法完成請求")


with open("wiki.md", "r", encoding="utf-8") as f:
    wiki_md = f.read()

if len(wiki_md) > 4500:
    wiki_md = wiki_md[:4500]
    log("[Node 0] 已讀取 wiki.md 知識庫（已控制在 4500 字元內以符合模型上下文）")
else:
    log("[Node 0] 已讀取 wiki.md 知識庫")

# ------------------------------------------------
# Loop 1：生成教學大綱 + Check 1（內容範圍與初學者適配檢查）
# ------------------------------------------------
outline = ""
outline_feedback = "無"

for attempt in range(1, 4):
    log(f"[Loop 1 - Attempt {attempt}] 生成 6 頁新手教學大綱...")
    outline = ask_llm(f"""
你是賽道教學助教。請「只依據」下方 Wiki 內容，為完全沒跑過賽道的新手設計一份 6 頁的《賽道胎壓與工作溫度基礎》教學簡報大綱。
要求：
1. 語氣親切、白話，讓零基礎新手看得懂。
2. 不得加入 Wiki 未提及的進階專有名詞或數據。

Wiki 內容：
{wiki_md}

前次審查回饋：{outline_feedback}
""")

    check1 = ask_llm(
        f"""
請嚴格審查以下教學大綱：
1. 是否 100% 基於提供的 Wiki，沒有自行加入 Wiki 以外的專有名詞或數據？
2. 是否適合完全沒跑過賽道的新手理解？

若完全通過，只回覆「PASS」；若有問題，請回覆「FAIL: 具體原因」。

大綱：
{outline}

Wiki：
{wiki_md}
""",
        model=ACTIVE_MODEL,
        temp=0.1,
    ).strip()

    log(f"[Check 1 Result] {check1}")
    if "PASS" in check1:
        break
    outline_feedback = check1

# ------------------------------------------------
# Loop 2：生成 HTML 簡報 + Check 2（程式碼結構與互動功能檢查）
# ------------------------------------------------
html_out = ""
html_feedback = "無"

for attempt in range(1, 4):
    log(f"[Loop 2 - Attempt {attempt}] 生成單檔互動式 HTML 簡報...")
    raw_html = ask_llm(
        f"""
請根據以下大綱與 Wiki 內容，製作一份「單一檔案」的教學型 HTML 簡報（繁體中文）。
要求：
1. 全螢幕單頁切換排版（每頁 <section class="slide">，一次只顯示一頁），字體清晰易讀（至少 22px 以上）。
2. 內建 CSS 與 JavaScript：支援鍵盤左右方向鍵（ArrowLeft / ArrowRight）與按鈕切換上下頁，並顯示目前頁數（如 1 / 6）。
3. 只輸出純 HTML 程式碼，不要加 ```html 或 ``` 標記，也不要任何額外說明文字。

教學大綱：
{outline}

參考 Wiki：
{wiki_md}

前次結構檢查回饋：{html_feedback}
""",
        model=ACTIVE_MODEL,
        temp=0.3,
    )

    cleaned = raw_html.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    has_end = "</html>" in cleaned.lower()
    slide_cnt = cleaned.lower().count('class="slide"')
    has_nav = ("arrowright" in cleaned.lower()) or ("keydown" in cleaned.lower())

    if has_end and slide_cnt >= 5 and has_nav:
        html_out = cleaned
        log(
            f"[Check 2 Result] PASS (slides={slide_cnt}, has_html_end={has_end}, has_nav={has_nav})"
        )
        break
    else:
        html_feedback = (
            f"結構未達標：has_html_end={has_end}, slide_count={slide_cnt}, has_nav={has_nav}"
        )
        log(f"[Check 2 Result] FAIL -> {html_feedback}")

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_out)

with open("execution_log.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(logs))

log("[Done] 已輸出 index.html 與 execution_log.txt")
