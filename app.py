#!/usr/bin/env python3
"""
EXTREME ALL-IN-ONE DEVELOPER BOT (Single Admin)
- Coding help / Learning
- Memory storage / Retrieval
- General knowledge queries
- 24/7 auto-restart
- Colorful logs
Optimized for low-RAM VPS / Katabump
"""

# -------------------- IMPORTS --------------------
import os, re, time, sqlite3, shutil, ast, tempfile, subprocess, resource
from typing import List, Dict, Optional
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# -------------------- COLORFUL LOGGING --------------------
import logging
from colorama import init as colorama_init, Fore, Style
colorama_init(autoreset=True)
logger = logging.getLogger("ExtremeDevBot")
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
formatter = logging.Formatter(
    Fore.CYAN + "[%(asctime)s]" + 
    Fore.YELLOW + " [%(levelname)s] " + 
    Fore.GREEN + "%(message)s" + Style.RESET_ALL
)
ch.setFormatter(formatter)
logger.addHandler(ch)
def log_info(msg): logger.info(msg)
def log_warn(msg): logger.warning(msg)
def log_error(msg): logger.error(msg)

# -------------------- ENV & CONFIG --------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing in .env")
if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID missing in .env")

HEADERS = {"User-Agent":"Mozilla/5.0 (compatible; ExtremeDevBot/2.0)"}

# -------------------- PANEL-SAFE LIMITS --------------------
MAX_PAGE_SIZE = 800_000
CRAWL_TIMEOUT = 10
REQUEST_DELAY = 1.2
CACHE_LIMIT = 20
PY_SANDBOX_TIMEOUT = 3
PY_SANDBOX_MEM_BYTES = 128*1024*1024
DB_FILE = "extreme_free_dev_bot.db"

def auto_set_limits():
    try: st=shutil.disk_usage(".").free//(1024*1024)
    except: st=700
    allowed_db_mb=max(50,int(st*0.4))
    max_pages=max(2,min(12,allowed_db_mb//8))
    return {"MAX_PAGES_PER_LEARN":max_pages,"ALLOWED_DB_MB":allowed_db_mb}

limits=auto_set_limits()
MAX_PAGES_PER_LEARN=limits["MAX_PAGES_PER_LEARN"]

# -------------------- DATABASE --------------------
conn=sqlite3.connect(DB_FILE,check_same_thread=False)
cur=conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS docs_idx (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 topic TEXT,
 title TEXT,
 url TEXT UNIQUE,
 snippet TEXT,
 content TEXT,
 source TEXT,
 crawled INTEGER
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS memory (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 key TEXT,
 value TEXT,
 source TEXT,
 created INTEGER
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS messages (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 chat_id INTEGER,
 text TEXT,
 created INTEGER
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS review_queue (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 chat_id INTEGER,
 prompt TEXT,
 response TEXT,
 approved INTEGER,
 created INTEGER
)""")
conn.commit()

def db_size_ok():
    try:
        size=os.path.getsize(DB_FILE)
        return size<300*1024*1024
    except: return True

# -------------------- CACHE & SAFE GET --------------------
cache={}
def safe_get(url,timeout=CRAWL_TIMEOUT):
    try:
        r=requests.get(url,headers=HEADERS,timeout=timeout,stream=True)
        r.raise_for_status()
        data=r.raw.read(MAX_PAGE_SIZE,decode_content=True)
        return data
    except: return b""

def cached_get(url):
    if url in cache: return cache[url]
    html_bytes=safe_get(url)
    if html_bytes:
        if len(cache)>=CACHE_LIMIT: cache.pop(next(iter(cache)))
        cache[url]=html_bytes
    return html_bytes

# -------------------- MEMORY --------------------
def memory_save(key,value,source="user"):
    cur.execute("INSERT INTO memory (key,value,source,created) VALUES (?,?,?,?)",
                (key,value,source,int(time.time())))
    conn.commit()
def memory_get(key_substr):
    cur.execute("SELECT id,key,value FROM memory WHERE key LIKE ? ORDER BY created DESC LIMIT 20",
                (f"%{key_substr}%",))
    return cur.fetchall()

# -------------------- INDEX --------------------
def index_insert(topic,title,url,snippet,content,source):
    cur.execute("""INSERT OR IGNORE INTO docs_idx
        (topic,title,url,snippet,content,source,crawled)
        VALUES (?,?,?,?,?,?,?)""",
        (topic,title,url,snippet[:1000],content[:4000],source,int(time.time())))
    conn.commit()

def index_search(topic,query,limit=6):
    cur.execute("""SELECT title,url,snippet FROM docs_idx
                   WHERE topic=? AND (content LIKE ? OR snippet LIKE ?)
                   ORDER BY crawled DESC LIMIT ?""",
                (topic,f"%{query}%",f"%{query}%",limit))
    rows=cur.fetchall()
    if rows: return rows
    cur.execute("""SELECT title,url,snippet FROM docs_idx
                   WHERE content LIKE ? OR snippet LIKE ?
                   ORDER BY crawled DESC LIMIT ?""",
                (f"%{query}%",f"%{query}%",limit))
    return cur.fetchall()

# -------------------- FETCHERS --------------------
def fetch_duckduckgo(query):
    q=quote_plus(query)
    url=f"https://html.duckduckgo.com/html/?q={q}"
    html_bytes=cached_get(url)
    if not html_bytes: return []
    soup=BeautifulSoup(html_bytes,"lxml",from_encoding="utf-8")
    results=[]
    for a in soup.select(".result__a")[:6]:
        title=a.get_text(strip=True)
        link=a.get("href")
        snippet_tag=a.parent.select_one(".result__snippet")
        snippet=snippet_tag.get_text(strip=True) if snippet_tag else ""
        results.append({"title":title,"link":link,"snippet":snippet})
    return results

def crawl_page(url):
    html_bytes=cached_get(url)
    if not html_bytes: return {}
    soup=BeautifulSoup(html_bytes,"lxml",from_encoding="utf-8")
    title=soup.title.text.strip() if soup.title else "Untitled"
    text=soup.get_text(separator=" ")
    cleaned=re.sub(r"\s+"," ",text)
    return {"title":title,"content":cleaned}

# -------------------- DEEP THINK --------------------
SOURCE_WEIGHTS={"duckduckgo":1.0,"mdn":1.8,"w3schools":1.0,"freecodecamp":1.6,"github":1.4,"stackoverflow":1.5,"tensorflow":1.9,"pytorch":1.9}
def score_sources(dom): return SOURCE_WEIGHTS.get(dom.lower(),1.0)

def extract_code_snippets_from_text(text,lang_hint="python"):
    snippets=[]
    for m in re.finditer(r"```(?:%s)?\\n(.*?)```"%re.escape(lang_hint),text,flags=re.S|re.I):
        snippets.append(m.group(1).strip())
    for m in re.finditer(r"```\\n(.*?)```",text,flags=re.S):
        snippets.append(m.group(1).strip())
    for m in re.finditer(r"(?:\\n\\s{4,}.*?)(?=\\n\\S|\\Z)",text,flags=re.S):
        block="\n".join([line[4:] for line in m.group(0).splitlines()])
        if len(block)>20: snippets.append(block.strip())
    unique=[]
    for s in snippets:
        if s and s not in unique: unique.append(s)
    return unique

def python_syntax_check(code):
    try: ast.parse(code); return None
    except Exception as e: return str(e)

def run_in_python_sandbox(code,timeout=3,mem_bytes=128*1024*1024):
    with tempfile.TemporaryDirectory() as td:
        pyfile=os.path.join(td,"t.py")
        with open(pyfile,"w",encoding="utf-8") as f: f.write(code)
        runner=f"""import resource,sys,runpy
try:
 resource.setrlimit(resource.RLIMIT_AS,({mem_bytes},{mem_bytes}))
 resource.setrlimit(resource.RLIMIT_DATA,({mem_bytes},{mem_bytes}))
except: pass
try: runpy.run_path("{pyfile}", run_name="__main__")
except SystemExit as e: sys.exit(getattr(e,'code',0))"""
        runner_file=os.path.join(td,"run.py")
        with open(runner_file,"w",encoding="utf-8") as f: f.write(runner)
        try:
            proc=subprocess.run(["python3",runner_file],capture_output=True,text=True,timeout=timeout)
            return (proc.returncode==0,proc.stdout,proc.stderr,False)
        except subprocess.TimeoutExpired as e:
            return (False,e.stdout or "",e.stderr or "Timed out",True)
        except Exception as e:
            return (False,"",f"Sandbox error: {e}",False)

# -------------------- SYNTHESIZE & VALIDATE --------------------
def synthesize_and_validate(lang,query_text,indexed_docs):
    snippet_candidates=[]
    provenance=[]
    for title,url,snip in indexed_docs:
        try:
            html_bytes=cached_get(url)
            if not html_bytes: continue
            text=BeautifulSoup(html_bytes,"lxml",from_encoding="utf-8").get_text(separator=" ")
            codes=extract_code_snippets_from_text(text,lang_hint=lang)
            for c in codes: snippet_candidates.append((c,url,title))
            provenance.append({"title":title,"url":url,"snippet":snip[:400]})
        except: continue
    counts={}
    for c,url,title in snippet_candidates:
        key=c.strip()
        counts.setdefault(key,{"count":0,"sources":set()})
        counts[key]["count"]+=1
        counts[key]["sources"].add(url)
    if not counts:
        text_summary="\n\n".join([p["snippet"] for p in provenance[:6]])
        return {"answer":text_summary or "No code found.","provenance":provenance,"confidence":0.2,"validation":None}
    scored=[]
    for code,meta in counts.items():
        freq=meta["count"]
        weights=sum([score_sources(urlparse(s).netloc) for s in meta["sources"]])
        avg_weight=weights/max(1,len(meta["sources"]))
        score=freq*avg_weight
        scored.append((score,code,list(meta["sources"])))
    scored.sort(reverse=True,key=lambda x:x[0])
    top_score,top_code,top_sources=scored[0]
    validation={"lang":lang,"syntax_error":None,"exec_ok":None,"exec_stdout":"","exec_stderr":"","timed_out":False}
    if lang.lower()=="python":
        syntax_err=python_syntax_check(top_code)
        validation["syntax_error"]=syntax_err
        if not syntax_err:
            ok,out,err,timed=run_in_python_sandbox(top_code)
            validation.update({"exec_ok":ok,"exec_stdout":out[:2000],"exec_stderr":err[:2000],"timed_out":timed})
    confidence=min(0.99,0.2+(top_score/(1.0+top_score)))
    if validation["syntax_error"]: confidence*=0.2
    elif validation.get("exec_ok") is False: confidence*=0.6
    answer_text=f"Top candidate (score={top_score:.2f}, confidence={confidence:.2f}):\n\n```{lang}\n{top_code[:10000]}\n```"
    return {"answer":answer_text,"provenance":top_sources[:6],"confidence":confidence,"validation":validation}

# -------------------- COMMAND HANDLERS --------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I'm your upgraded EXTREME Developer Assistant Bot.")

async def learn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db_size_ok():
        return await update.message.reply_text("⚠️ DB too large. Use /clearmemory.")
    if not context.args: return await update.message.reply_text("Usage: /learn <topic>")
    topic=" ".join(context.args)
    await update.message.reply_text(f"🔍 Learning about *{topic}*...",parse_mode="Markdown")
    results=fetch_duckduckgo(topic+" programming tutorial")
    if not results: return await update.message.reply_text("No results found.")
    crawled_count=0
    for r in results:
        if crawled_count>=MAX_PAGES_PER_LEARN: break
        url=r["link"]
        data=crawl_page(url)
        if not data: continue
        index_insert(topic,data["title"],url,r.get("snippet",""),data["content"],"duckduckgo")
        crawled_count+=1
        time.sleep(REQUEST_DELAY)
    await update.message.reply_text(f"📚 Learned {crawled_count} pages for topic: {topic}")

async def codehelp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args)<2:
        return await update.message.reply_text("Usage: /codehelp <language> <topic>")
    lang=context.args[0].lower()
    topic=" ".join(context.args[1:]).lower()
    rows=index_search(lang,topic)
    if not rows: return await update.message.reply_text("No indexed docs. Try /learn first.")
    result=synthesize_and_validate(lang,topic,rows)
    reply=result["answer"]+"\n\n*Confidence:* {:.2f}\n".format(result["confidence"])
    reply+="\n*Sources:*\n"+"\n".join(result["provenance"])
    val=result.get("validation")
    if val:
        reply+="\n\n*Validation:*\n"
        if val.get("syntax_error"):
            reply+=f"• Syntax error: {val['syntax_error']}\n"
        else:
            if val.get("exec_ok") is True:
                reply+="• Execution: OK (small test run)\n"
                if val.get("exec_stdout"):
                    reply+=f"  stdout: ```\n{val['exec_stdout'][:800]}\n```\n"
            elif val.get("exec_ok") is False:
                reply+="• Execution: FAILED or timed out\n"
                if val.get("exec_stderr"):
                    reply+=f"  stderr: ```\n{val['exec_stderr'][:800]}\n```\n"
    await update.message.reply_text(reply,parse_mode="Markdown")
    if result["confidence"]<0.5 or (val and (val.get("syntax_error") or val.get("exec_ok") is False or val.get("timed_out"))):
        cur.execute("INSERT INTO review_queue (chat_id,prompt,response,approved,created) VALUES (?,?,?,?,?)",
                    (update.effective_chat.id,topic,result["answer"],0,int(time.time())))
        conn.commit()

async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: /search <query>")
    query=" ".join(context.args)
    results=fetch_duckduckgo(query)
    if not results: return await update.message.reply_text("No results.")
    out=f"🔍 **Search results for:** {query}\n\n"
    for r in results: out+=f"• *{r['title']}*\n  {r['snippet']}\n  🔗 {r['link']}\n\n"
    await update.message.reply_text(out,parse_mode="Markdown")

async def memorysave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args)<2: return await update.message.reply_text("Usage: /memorysave <key> <value>")
    key=context.args[0]; value=" ".join(context.args[1:])
    memory_save(key,value)
    await update.message.reply_text("Saved.")

async def memoryget_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: /memoryget <key>")
    key=" ".join(context.args); rows=memory_get(key)
    if not rows: return await update.message.reply_text("No matches.")
    out="🧠 *Memory matches:*\n\n"
    for _id,k,v in rows: out+=f"• `{k}` → {v}\n"
    await update.message.reply_text(out,parse_mode="Markdown")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return await update.message.reply_text("Not authorized.")
    size=os.path.getsize(DB_FILE)/1024/1024; cur.execute("SELECT COUNT(*) FROM docs_idx"); docs=cur.fetchone()[0]
    await update.message.reply_text(f"📊 DB Size: {size:.2f} MB\n📚 Indexed Docs: {docs}")

async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: /ask <topic>")
    topic=" ".join(context.args)
    log_info(f"User asked general topic: {topic}")
    results=fetch_duckduckgo(topic)
    if not results: return await update.message.reply_text("No results found.")
    summary=f"🔍 *Top results for:* {topic}\n\n"
    for r in results[:5]:
        summary+=f"• *{r['title'][:150]}*\n  {r['snippet'][:300]}\n  🔗 {r['link']}\n\n"
    await update.message.reply_text(summary,parse_mode="Markdown")

# -------------------- BOT RUN --------------------
def main():
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start_cmd))
    app.add_handler(CommandHandler("learn",learn_cmd))
    app.add_handler(CommandHandler("codehelp",codehelp_cmd))
    app.add