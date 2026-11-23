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


def ask_llm(prompt: str, model: str = "llama-3.3-70b-versatile", temp: float = 0.3) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temp,
    )
    return resp.choices[0].message.content or ""


with open("wiki.md", "r", encoding="utf-8") as f:
    wiki_md = f.read()

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
        model="llama-3.1-8b-instant",
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
        model="llama-3.3-70b-versatile",
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
