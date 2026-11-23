import os
import time
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
        "qwen/qwen3.8-27b",
        "qwen/qwen3-32b",
        "llama-3.3-70b-versatile",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
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


def ask_llm(prompt: str, model: str = ACTIVE_MODEL, temp: float = 0.3, max_tokens: int = 900) -> str:
    current_prompt = prompt
    current_max_tokens = max_tokens
    for attempt in range(1, 6):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": current_prompt}],
                temperature=temp,
                max_tokens=current_max_tokens,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            err_msg = str(e).lower()
            log(f"[LLM Retry {attempt}] 呼叫發生狀況: {e}")
            if "429" in err_msg or "rate_limit" in err_msg:
                # 壓低 max_tokens 並等待 35 秒讓每分鐘 Token 額度重置
                current_max_tokens = min(current_max_tokens, 800)
                log(f"[Rate Limit Guard] 觸發 429，將 max_tokens 降至 {current_max_tokens} 並等待 35 秒...")
                time.sleep(35)
            elif "reduce the length" in err_msg or "too large" in err_msg or "tokens" in err_msg:
                cut_len = max(1200, int(len(current_prompt) * 0.65))
                current_prompt = current_prompt[:cut_len] + "\n\n[已縮短以符合長度限制]"
                time.sleep(3)
            else:
                time.sleep(3)
    raise RuntimeError("多次重試後仍無法完成 LLM 請求")


with open("wiki.md", "r", encoding="utf-8") as f:
    wiki_md = f.read()

if len(wiki_md) > 3200:
    wiki_md = wiki_md[:3200]
    log("[Node 0] 已讀取 wiki.md 知識庫（已控制在 3200 字元內以保留足夠上下文空間）")
else:
    log("[Node 0] 已讀取 wiki.md 知識庫")

# ------------------------------------------------
# Loop 1：生成教學大綱 + Check 1（內容範圍與初學者適配檢查）
# ------------------------------------------------
outline = ""
outline_feedback = "無"

for attempt in range(1, 4):
    log(f"[Loop 1 - Attempt {attempt}] 生成 6 頁新手教學大綱...")
    outline = ask_llm(
        f"""
你是賽道教學助教。請「只依據」下方 Wiki 內容，為完全沒跑過賽道的新手設計一份 6 頁的《賽道胎壓與工作溫度基礎》教學簡報大綱。
要求：
1. 語氣親切、白話，讓零基礎新手看得懂。
2. 不得加入 Wiki 未提及的進階專有名詞、具體 PSI 數值或自行捏造的表格名稱。

Wiki 內容：
{wiki_md}

前次審查回饋：{outline_feedback[:300]}
""",
        max_tokens=850,
    )

    check1 = ask_llm(
        f"""
請嚴格審查以下教學大綱：
1. 是否 100% 基於提供的 Wiki，沒有自行加入 Wiki 以外的專有名詞或數據？
2. 是否適合完全沒跑過賽道的新手理解？

請精簡作答（不超過 120 字）：若通過回覆「PASS」；若未通過，回覆「FAIL: 原因」。

大綱：
{outline[:1500]}

Wiki：
{wiki_md[:2000]}
""",
        model=ACTIVE_MODEL,
        temp=0.1,
        max_tokens=300,
    ).strip()

    short_check1 = check1.replace("\n", " ")[:300]
    log(f"[Check 1 Result] {short_check1}")
    if "PASS" in check1.upper() and "FAIL" not in check1.upper():
        break
    outline_feedback = short_check1

# 等待一下避免緊接著打爆 OTPM
time.sleep(15)

# ------------------------------------------------
# Loop 2：生成 HTML 簡報 + Check 2（程式碼結構與互動功能檢查）
# ------------------------------------------------
html_out = ""
html_feedback = "無"

for attempt in range(1, 4):
    log(f"[Loop 2 - Attempt {attempt}] 生成單檔互動式 HTML 簡報...")
    raw_html = ask_llm(
        f"""
請根據以下大綱，製作一份精簡、完整的「單一檔案」教學型 HTML 簡報（繁體中文）。
要求：
1. 全螢幕單頁切換排版（每頁 <section class="slide">，共 6 頁，一次只顯示一頁），字體清晰易讀（至少 22px 以上）。
2. 內建簡潔 CSS 與 JavaScript：支援鍵盤左右方向鍵（ArrowLeft / ArrowRight）與上下頁按鈕切換，並顯示目前頁數（如 1 / 6）。
3. 程式碼務必精簡，確保完整輸出到 </html>，不要加 ```html 標記或額外說明文字。

教學大綱：
{outline[:1500]}

前次結構檢查回饋：{html_feedback[:200]}
""",
        model=ACTIVE_MODEL,
        temp=0.3,
        max_tokens=900,
    )

    cleaned = raw_html.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    # 若模型輸出接近結尾但漏了 </html>，補上閉合標籤方便驗證
    if "<html" in cleaned.lower() and "</html>" not in cleaned.lower():
        if "</body>" not in cleaned.lower():
            cleaned += "\n</body>"
        cleaned += "\n</html>"

    html_out = cleaned
    has_end = "</html>" in cleaned.lower()
    slide_cnt = cleaned.lower().count('class="slide"')
    has_nav = ("arrowright" in cleaned.lower()) or ("keydown" in cleaned.lower())

    if has_end and slide_cnt >= 5 and has_nav:
        log(
            f"[Check 2 Result] PASS (slides={slide_cnt}, has_html_end={has_end}, has_nav={has_nav})"
        )
        break
    else:
        html_feedback = (
            f"結構未達標：has_html_end={has_end}, slide_count={slide_cnt}, has_nav={has_nav}"
        )
        log(f"[Check 2 Result] FAIL -> {html_feedback}")
        time.sleep(20)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_out)

with open("execution_log.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(logs))

log("[Done] 已輸出 index.html 與 execution_log.txt")
