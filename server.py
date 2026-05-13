#!/usr/bin/env python3
"""照片日记 API — 激活码验证 + 硅基流动视觉模型调用"""

import json, os, re, hashlib, secrets, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from pathlib import Path

# ── Config ──────────────────────────────────────────────
PORT = int(os.environ.get("PORT", "8888"))
PROJECT_DIR = Path(__file__).parent.resolve()
CODES_FILE = PROJECT_DIR / "codes.json"

SF_KEY = ""
SF_MODEL = "Qwen/Qwen3-VL-30B-A3B-Instruct"

def load_sf_key():
    p = Path.home() / ".config" / "siliconflow" / "api_key"
    if p.exists():
        return p.read_text().strip()
    return os.environ.get("SF_KEY") or os.environ.get("SILICONFLOW_API_KEY") or ""

SF_KEY = load_sf_key()

def load_codes():
    if CODES_FILE.exists():
        return json.loads(CODES_FILE.read_text())
    return {}

SYSTEM_PROMPT = """你是一位细腻的私人日记写手。你将收到用户今天拍摄的几张照片，你的任务是基于这些照片写一篇第一人称日记。

规则：
1. 以"我"的口吻写，像用户本人当晚写的日记
2. 观察照片中的细节：光线、构图、人物、场景、氛围、情绪
3. 从照片顺序推断今天的时间线，串联成一天的叙事
4. 侧重感官描述（看到什么、感受到什么），不要编造照片里没有的事件
5. 语言自然、简洁，带一点文学感但不做作，约 300-600 字
6. 用 Markdown 格式：日记正文不需要标题，段落间空一行即可
7. 不要把每张照片孤立描述——要融成一个整体的一天的故事"""


class DiaryAPI(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/":
            self._json({"service": "照片日记 API", "version": "2.0"})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/diary":
            self._handle_diary()
        elif self.path == "/api/activate":
            self._handle_activate()
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-License-Key")
        self.end_headers()

    # ── Activate ──────────────────────────────────────────

    def _handle_activate(self):
        try:
            body = self._read_body()
            code = body.get("code", "").strip()
            if not code:
                self._json({"valid": False, "error": "请输入激活码"}, 400)
                return

            codes = load_codes()
            entry = codes.get(code)

            if not entry:
                self._json({"valid": False, "error": "激活码无效"}, 400)
                return

            if entry.get("used"):
                self._json({"valid": False, "error": "该激活码已被使用"}, 400)
                return

            # First use: mark as used
            entry["used"] = True
            entry["activated_at"] = datetime.now().isoformat()
            CODES_FILE.write_text(json.dumps(codes, ensure_ascii=False, indent=2))

            print(f"[Activate] Code {code[:8]}... activated")
            self._json({"valid": True})

        except Exception as e:
            import traceback; traceback.print_exc()
            self._json({"valid": False, "error": str(e)}, 500)

    # ── Diary ─────────────────────────────────────────────

    def _handle_diary(self):
        try:
            body = self._read_body()
            photos = body.get("photos", [])
            date_str = body.get("date", "")

            if not photos:
                self._json({"error": "请至少选择一张照片"}, 400)
                return

            # Normalize photos
            normalized = []
            for p in photos:
                if isinstance(p, str):
                    normalized.append({"dataUrl": p, "timestamp": ""})
                else:
                    normalized.append(p)
            photos = normalized

            # Validate license
            license_key = self.headers.get("X-License-Key", "")
            if not self._validate_license(license_key):
                self._json({"error": "请购买激活码后使用"}, 403)
                return

            if not SF_KEY:
                self._json({"error": "服务未配置 API key"}, 500)
                return

            print(f"[Diary] {len(photos)} photos, date={date_str}")
            diary, model, tokens = self._call_siliconflow(photos, date_str)
            print(f"[Diary] Done. model={model}, tokens={tokens}")

            self._json({"diary": diary, "model": model, "tokens": tokens})

        except Exception as e:
            import traceback; traceback.print_exc()
            self._json({"error": f"生成失败: {str(e)}"}, 500)

    def _validate_license(self, key):
        if not key:
            return True  # Allow trial (frontend enforces count)
        codes = load_codes()
        entry = codes.get(key)
        return entry is not None  # Valid code = licensed

    def _call_siliconflow(self, photos, date_str):
        import urllib.request as ur

        photo_desc = []
        for i, p in enumerate(photos):
            ts = p.get("timestamp", "")
            ts_str = f"，拍摄时间：{ts}" if ts else ""
            photo_desc.append(f"照片{i+1}{ts_str}")
        time_hint = "以下是按时间顺序排列的照片：\n" + "\n".join(photo_desc)

        user_content = [{
            "type": "text",
            "text": f"今天日期：{date_str}\n{time_hint}\n\n请根据这些照片的具体拍摄时间，串联成一天的故事来写一篇日记。如果照片没有时间戳，则根据照片内容推断先后顺序。"
        }]
        for p in photos:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": p["dataUrl"]},
            })

        payload = json.dumps({
            "model": SF_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": 2048,
            "temperature": 0.7,
        }).encode("utf-8")

        req = ur.Request(
            "https://api.siliconflow.cn/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {SF_KEY}",
            },
        )
        resp = json.loads(ur.urlopen(req, timeout=120).read())

        diary = resp["choices"][0]["message"]["content"]
        tokens = resp["usage"]["total_tokens"]
        model = resp["model"]
        return diary, model, tokens

    # ── Helpers ───────────────────────────────────────────

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length))

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")


if __name__ == "__main__":
    if not SF_KEY:
        print("WARNING: SF_KEY not set. Set SILICONFLOW_API_KEY env var or ~/.config/siliconflow/api_key")
    print(f"照片日记 API v2.0 :{PORT}")
    server = HTTPServer(("0.0.0.0", PORT), DiaryAPI)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
