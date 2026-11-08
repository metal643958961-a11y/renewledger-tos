"""Renew Ledger, a single-household subscription register."""
import base64
import calendar
import hmac
import os
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

DATA = Path(os.environ.get("LEDGER_DATA", "/data"))
TOKEN = secrets.token_urlsafe(32)
CYCLES = {"month": "每月", "year": "每年"}
STYLE = """*{box-sizing:border-box}body{margin:0;background:#f6f5ee;color:#233933;font:16px/1.55 system-ui,sans-serif}main{max-width:800px;margin:auto;padding:6vh 16px}h1{font-size:2.2rem;margin:0}section,article{padding:16px;background:white;border:1px solid #d1ddd4;border-radius:10px;margin:12px 0}p{margin:6px 0}input,select,button,a{font:inherit}input,select,button{padding:7px 10px;border:1px solid #92a89b;border-radius:5px;max-width:100%}button,.add{color:white;background:#215b49;cursor:pointer}a{color:#215b49}.add{padding:7px 12px;border-radius:5px;text-decoration:none}.row{display:flex;align-items:center;flex-wrap:wrap;gap:12px}label{display:grid;gap:4px;margin:12px 0}small{color:#52655b}h2{font-size:1.2rem;margin:0}.danger{color:#863832}"""


def connection():
    db = sqlite3.connect(DATA / "ledger.db", timeout=5)
    db.row_factory = sqlite3.Row
    return db


def initialize():
    global AUTH
    os.umask(0o077)
    password_file = DATA / "password.txt"
    if not password_file.exists():
        with password_file.open("x") as f:
            f.write(secrets.token_urlsafe(24) + "\n")
    password = password_file.read_text().strip()
    if len(password) < 16:
        raise ValueError("password.txt 至少需要 16 个字符")
    AUTH = b"Basic " + base64.b64encode(("admin:" + password).encode())
    with closing(connection()) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, cents INTEGER NOT NULL,
            cycle TEXT NOT NULL, due TEXT NOT NULL, anchor INTEGER NOT NULL, rev INTEGER NOT NULL DEFAULT 1)""")


def advance(row):
    due = date.fromisoformat(row["due"])
    month_index = due.year * 12 + due.month - 1 + (1 if row["cycle"] == "month" else 12)
    year, month = divmod(month_index, 12)
    return date(year, month + 1, min(row["anchor"], calendar.monthrange(year, month + 1)[1]))


def fields(raw):
    return dict(parse_qsl(raw, keep_blank_values=True, max_num_fields=10, errors="strict"))


def page(title, body):
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1"><title>' + title +
            '</title><style>' + STYLE + '</style><main><h1>' + title + '</h1>' + body + '</main></html>')


def hidden(row=None):
    values = {"csrf": TOKEN}
    if row:
        values.update(id=row["id"], rev=row["rev"])
    return "".join(f'<input type="hidden" name="{k}" value="{v}">' for k, v in values.items())


def form(row):
    name, price, due, cycle = "", "", "", "month"
    if row:
        name, price = escape(row["name"], quote=True), f'{row["cents"]/100:.2f}'
        due, cycle = row["due"], row["cycle"]
    options = "".join(f'<option value="{k}" {"selected" if k == cycle else ""}>{v}</option>' for k,v in CYCLES.items())
    return page("编辑订阅" if row else "新增订阅", f"""<section><form method="post" action="/save">{hidden(row)}
<label>服务名称<input required maxlength="80" name="name" value="{name}"></label>
<label>每期金额（人民币元）<input required type="number" name="price" min="0" max="99999999.99" step=".01" value="{price}"></label>
<label>扣费周期<select name="cycle">{options}</select></label>
<label>下次续费日<input required type="date" name="due" value="{due}"></label>
<div class="row"><button>保存订阅</button><a href="/">取消</a></div></form></section>""")


def overview(db, query):
    q = query.get("q", "").strip()
    today = datetime.now(timezone(timedelta(hours=8))).date()
    rows = db.execute("SELECT * FROM subscriptions WHERE instr(lower(name),lower(?)) > 0 ORDER BY due,id", (q,))
    annual = db.execute("SELECT sum(cents * CASE cycle WHEN 'month' THEN 12 ELSE 1 END) FROM subscriptions").fetchone()[0] or 0
    cards = []
    for r in rows:
        days = (date.fromisoformat(r["due"]) - today).days
        status = f"已逾期 {-days} 天" if days < 0 else ("今天到期" if days == 0 else f"{days} 天后")
        cards.append(f"""<article><h2>{escape(r['name'])}</h2><p>¥{r['cents']/100:.2f} · {CYCLES[r['cycle']]}</p>
<p>{r['due']} · {status}</p><div class="row"><form method="post" action="/renew">{hidden(r)}
<button>已续一期</button></form><a href="/edit?id={r['id']}">编辑</a>
<a class="danger" href="/delete?id={r['id']}">删除</a></div></article>""")
    return page("个人订阅台账", f"""<section><p>全部订阅折合年支出</p><strong>¥{annual/100:,.2f}</strong>
<small>按当前价格和扣费周期估算</small></section><div class="row"><form action="/">
<input aria-label="服务名称" name="q" placeholder="查找服务名称" value="{escape(q, quote=True)}"><button>查询</button>
</form><a class="add" href="/new">新增订阅</a></div>""" + ("".join(cards) or "<p>没有符合条件的订阅。</p>"))


class Handler(BaseHTTPRequestHandler):
    timeout = 8

    def log_request(self, *args):
        pass

    def reply(self, status, body="", **headers):
        raw = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        if hmac.compare_digest(self.headers.get("Authorization", "").encode(), AUTH):
            return True
        self.reply(401, "请使用管理员凭据登录。", **{"WWW-Authenticate": 'Basic realm="Renew Ledger"'})
        return False

    def do_GET(self):
        if self.path == "/health":
            return self.reply(200, "ok")
        if not self.authorized():
            return
        try:
            url = urlsplit(self.path)
            params = fields(url.query)
            with closing(connection()) as db:
                if url.path == "/":
                    return self.reply(200, overview(db, params))
                if url.path == "/new":
                    return self.reply(200, form(None))
                if url.path in ("/edit", "/delete"):
                    row = db.execute("SELECT * FROM subscriptions WHERE id=?", (params.get("id"),)).fetchone()
                    if row:
                        body = form(row) if url.path == "/edit" else page("删除订阅",
                            f'<section><p>确认删除「{escape(row["name"])}」？</p><form method="post" action="/delete">{hidden(row)}<button>确认删除</button> <a href="/">取消</a></form></section>')
                        return self.reply(200, body)
            self.reply(404, "没有找到该记录或页面。")
        except ValueError:
            self.reply(400, "查询参数无效。")

    def do_POST(self):
        if not self.authorized():
            return
        if self.path not in ("/save", "/renew", "/delete"):
            return self.reply(404)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096 or self.headers.get_content_type() != "application/x-www-form-urlencoded":
                return self.reply(400, "表单格式无效。")
            p = fields(self.rfile.read(size).decode())
            if not hmac.compare_digest(p.get("csrf","").encode(), TOKEN.encode()):
                return self.reply(403, "请刷新页面重试。")
            with closing(connection()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = None
                if "id" in p or self.path != "/save":
                    row = db.execute("SELECT * FROM subscriptions WHERE id=? AND rev=?", (p["id"],p["rev"])).fetchone()
                    if not row:
                        return self.reply(409, '记录已变化，请<a href="/">刷新台账</a>。')
                if self.path == "/delete":
                    db.execute("DELETE FROM subscriptions WHERE id=?", (row["id"],))
                elif self.path == "/renew":
                    db.execute("UPDATE subscriptions SET due=?, rev=rev+1 WHERE id=?", (advance(row).isoformat(),row["id"]))
                else:
                    name, price, cycle = p["name"].strip(), p["price"], p["cycle"]
                    due = date.fromisoformat(p["due"])
                    if not 1 <= len(name) <= 80 or cycle not in CYCLES or not re.fullmatch(r"[0-9]{1,8}(\.[0-9]{1,2})?",price):
                        raise ValueError()
                    anchor = row["anchor"] if row and row["due"] == due.isoformat() and row["cycle"] == cycle else due.day
                    values = (name,int(Decimal(price)*100),cycle,due.isoformat(),anchor)
                    if row:
                        db.execute("UPDATE subscriptions SET name=?,cents=?,cycle=?,due=?,anchor=?,rev=rev+1 WHERE id=?", values+(row["id"],))
                    else:
                        db.execute("INSERT INTO subscriptions(name,cents,cycle,due,anchor) VALUES(?,?,?,?,?)", values)
            self.reply(303, Location="/")
        except (ValueError, KeyError, OverflowError):
            self.reply(400, '字段无效，请返回表单检查名称、金额和日期。')
        except sqlite3.OperationalError:
            self.reply(503, '暂时无法写入，请检查存储空间后刷新台账。')


if __name__ == "__main__":
    initialize()
    ThreadingHTTPServer((os.environ.get("LEDGER_HOST","0.0.0.0"), int(os.environ.get("LEDGER_PORT","8080"))), Handler).serve_forever()
