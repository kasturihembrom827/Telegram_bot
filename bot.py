# -*- coding: utf-8 -*-
"""
🌹 XenRose Bot v9.0 Ultra (Stable GSMHost Build) + GSMHost Static-FFMPEG + Manual UPI Payment
Developer : Kasturi Hembrom
Website   : https://santaliwap.xyz
"""

import os
import re
import json
import random
import asyncio
import requests
import tempfile
import subprocess
import datetime
import uuid
from io import BytesIO
from PIL import Image, ImageFilter, ImageOps, ImageDraw, ImageFont

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
    InputFile,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from fpdf import FPDF

# ---------------- TOKEN ----------------
TOKEN = os.getenv("XENROSE_BOT_TOKEN", "")

# ---------------- DATA ----------------
DATA_FILE = "userdata.json"
data_store = {
    "xp": {},
    "warns": {},
    "pending_verifies": {},
    "vip": [],
    # new storage:
    "free_used": {},         # user_id -> {"date": "YYYY-MM-DD", "used": int}
    "premium": {},           # user_id -> {"until": "ISO_DATETIME"}
    "pending_payments": {},  # ref -> {"user_id": id, "amount": amt, "ts": iso, "note": "..."}
}

if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r") as f:
            loaded = json.load(f)
            # merge loaded keys into data_store (simple merge)
            for k, v in loaded.items():
                data_store[k] = v
    except Exception:
        pass


def save_store():
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data_store, f, indent=2)
    except Exception:
        pass


xp = data_store.setdefault("xp", {})
warns = data_store.setdefault("warns", {})
pending_verifies = data_store.setdefault("pending_verifies", {})
VIP = set(data_store.get("vip", []))

# ---------------- CONFIG ----------------
LINK_PATTERN = re.compile(r"(https?://|t\.me/|www\.)", re.IGNORECASE)
WHITELIST_DOMAINS = [
    "santaliwap.xyz",
    "santaliwap.xyz/page-free-theme",
    "santaliwap.xyz/page-premium-theme",
]

# FFMPEG (static binary inside project)
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "./ffmpeg/ffmpeg")

# Limits & payment
FREE_LIMIT_PER_DAY = int(os.getenv("FREE_LIMIT_PER_DAY", "5"))

# UPI ID fixed inside code as requested
UPI_ID = "6201235057@ptyes"
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)

# ---------------- FILE UPLOAD (Gofile) ----------------
def upload_to_drive(file_path, file_name):
    try:
        with open(file_path, "rb") as f:
            res = requests.post("https://store1.gofile.io/uploadFile", files={"file": f})
            j = res.json()
            if j.get("status") == "ok" and j.get("data"):
                return j["data"].get("downloadPage") or j["data"].get("link") or "✅ Uploaded (no link)"
    except Exception:
        pass
    return "❌ Upload failed"

# ---------------- HELPERS ----------------
def h(title):
    return f"🌟 {title}\n\n"


def line(text):
    return f"{text}\n"


async def is_admin(chat, user_id: int) -> bool:
    try:
        member = await chat.get_member(user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def load_font(size=48, bold=False):
    try:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


# Welcome card creator
def make_welcome_card(username: str, theme: str = "Movie") -> BytesIO:
    themes = {
        "Movie": {"bg": (12, 12, 16), "acc": (255, 64, 128), "sub": (0, 255, 200)},
        "Gaming": {"bg": (18, 0, 0), "acc": (240, 0, 0), "sub": (255, 255, 255)},
        "Love": {"bg": (255, 230, 240), "acc": (255, 64, 128), "sub": (140, 0, 60)},
        "Nature": {"bg": (5, 50, 30), "acc": (60, 220, 130), "sub": (210, 255, 230)},
    }
    t = themes.get(theme, themes["Movie"])
    W, H = 1024, 400
    img = Image.new("RGB", (W, H), t["bg"])
    draw = ImageDraw.Draw(img)
    for i in range(0, W, 4):
        alpha = int(60 * (1 - i / W))
        draw.line([(i, 0), (i, H)], fill=(t["acc"][0], t["acc"][1], t["acc"][2]), width=3)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 120))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    cx, cy, r = 170, H // 2, 90
    for o in range(12, 0, -1):
        draw.ellipse((cx - r - o, cy - r - o, cx + r + o, cy + r + o), outline=t["sub"], width=1)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(20, 20, 24))
    title_font = load_font(56, bold=True)
    name_font = load_font(46, bold=True)
    sub_font = load_font(28, bold=False)
    title = "WELCOME TO THE GROUP"
    tw = draw.textlength(title, font=title_font)
    draw.text(((W - tw) / 2, 42), title, font=title_font, fill=t["acc"])
    uname = f"{username}"
    draw.text((300, 160), uname, font=name_font, fill=(255, 255, 255))
    sub = "Please verify below to start chatting."
    draw.text((300, 220), sub, font=sub_font, fill=t["sub"])
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf

# ---------------- USAGE / PREMIUM helpers ----------------
def today_iso():
    return datetime.datetime.utcnow().date().isoformat()


def increment_free_usage(user_id: int) -> int:
    key = str(user_id)
    fu = data_store.setdefault("free_used", {})
    rec = fu.get(key, {"date": today_iso(), "used": 0})
    if rec.get("date") != today_iso():
        rec = {"date": today_iso(), "used": 0}
    rec["used"] = rec.get("used", 0) + 1
    fu[key] = rec
    save_store()
    return rec["used"]


def get_free_usage(user_id: int) -> int:
    key = str(user_id)
    fu = data_store.get("free_used", {})
    rec = fu.get(key, {"date": today_iso(), "used": 0})
    if rec.get("date") != today_iso():
        return 0
    return rec.get("used", 0)


def set_premium(user_id: int, days: int):
    key = str(user_id)
    until = (datetime.datetime.utcnow() + datetime.timedelta(days=int(days))).isoformat()
    data_store.setdefault("premium", {})[key] = {"until": until}
    save_store()


def is_premium(user_id: int) -> bool:
    rec = data_store.get("premium", {}).get(str(user_id))
    if not rec:
        return False
    try:
        until = datetime.datetime.fromisoformat(rec["until"])
        if until > datetime.datetime.utcnow():
            return True
        else:
            data_store["premium"].pop(str(user_id), None)
            save_store()
            return False
    except Exception:
        return False


def grant_pending_payment(user_id: int, days: int):
    set_premium(user_id, days)


# ---------------- DECORATOR: ensure limit ----------------
def ensure_user_limit(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            return
        uid = user.id
        # Premiums & VIP bypass
        if is_premium(uid) or uid in VIP:
            return await func(update, context, *args, **kwargs)
        used = get_free_usage(uid)
        if used >= FREE_LIMIT_PER_DAY:
            await update.message.reply_text(f"Free daily limit ({FREE_LIMIT_PER_DAY}) reached. Upgrade to premium: /buy")
            return
        # increment then run
        increment_free_usage(uid)
        return await func(update, context, *args, **kwargs)
    return wrapper

# ---------------- START / MENU ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name if update.effective_user else "there"
    kb = [
        [InlineKeyboardButton("🎮 Fun", callback_data="fun"), InlineKeyboardButton("🧾 Tools", callback_data="tools")],
        [InlineKeyboardButton("⚙️ Admin", callback_data="admin"), InlineKeyboardButton("🏆 XP Stats", callback_data="xp")],
        [InlineKeyboardButton("🎨 Wapkiz Free Theme", url="https://santaliwap.xyz/page-free-theme/")],
        [InlineKeyboardButton("💎 Wapkiz Premium Theme", url="https://santaliwap.xyz/page-premium-theme/")],
        [InlineKeyboardButton("💬 Join Wapkiz Adda", url="https://t.me/wapkizadda")],
        [InlineKeyboardButton("🔒 Privacy", url="https://santaliwap.xyz/page-privacy.html")],
    ]
    await update.message.reply_text(
        f"""🌹 Welcome {name}! I'm XenRose Bot v9.0 Ultra 🌸

🤖 Group Helper + XP + Verify + Security
✨ New: Anti-Link • Auto Level-Up • Promote/Demote • VIP XP Boost • Welcome Card

💫 Commands: /help, /pdf, /convert, /sketch, /stats, /leaderboard, /warn, /ban, /mute, /promote, /demote

👩‍💻 Developer: Kasturi Hembrom
🌐 santaliwap.xyz
""",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    menus = {
        "fun": "🎮 Fun Commands:\n/joke /love <name> /roll",
        "tools": "🧰 Tools:\n/pdf <text> /convert <png|jpeg|webp> /sketch /vid2aud /audconv /vcompress",
        "admin": "⚙️ Admin:\n/ban /mute /warn /warnreset /clean /groupstats /promote /demote /verify_payment",
        "xp": "🏆 XP:\n/stats /leaderboard — Chat to earn XP! VIPs earn faster 🔥",
    }
    msg = menus.get(data)
    if msg:
        await q.message.reply_text(msg, parse_mode="Markdown")


# ---------------- ANTI-LINK / XP ----------------
def is_whitelisted(text: str) -> bool:
    return any(dom.lower() in text.lower() for dom in WHITELIST_DOMAINS)


async def anti_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text
    if await is_admin(update.effective_chat, update.effective_user.id):
        return
    if LINK_PATTERN.search(text) and not is_whitelisted(text):
        try:
            await update.message.delete()
        except Exception:
            pass
        uid = str(update.effective_user.id)
        warns[uid] = warns.get(uid, 0) + 1
        save_store()
        if warns[uid] >= 3:
            try:
                await update.message.chat.ban_member(update.effective_user.id)
            except Exception:
                pass
            warns[uid] = 0
            save_store()
            await context.bot.send_message(update.effective_chat.id, f"🚫 {update.effective_user.first_name} auto-banned (3 warnings).")
        else:
            await context.bot.send_message(update.effective_chat.id, f"⚠️ {update.effective_user.first_name}: Links not allowed! Warning {warns[uid]}/3")


async def give_xp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not (user and not user.is_bot):
        return
    text = update.message.text or ""
    # don't give xp for links that are not whitelisted
    if LINK_PATTERN.search(text) and not await is_admin(update.effective_chat, user.id):
        return
    uid = str(user.id)
    old_level = xp.get(uid, 0) // 100
    gain = 10 if user.id in VIP else 5
    xp[uid] = xp.get(uid, 0) + gain
    save_store()
    new_level = xp[uid] // 100
    if new_level > old_level:
        await update.message.reply_text(f"🔥 Level Up! {user.first_name} reached Level {new_level} 🏆 (+{gain} XP)", parse_mode="Markdown")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    user_xp = xp.get(uid, 0)
    level = user_xp // 100
    rate = "VIP ×2" if update.effective_user.id in VIP else "Normal"
    await update.message.reply_text(h("Your Stats") + line(f"XP: {user_xp}") + line(f"Level: {level}") + line(f"Rate: {rate}"), parse_mode="Markdown")


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not xp:
        return await update.message.reply_text("No XP data yet.")
    sorted_xp = sorted(xp.items(), key=lambda x: x[1], reverse=True)[:10]
    board = h("XP Leaderboard")
    for i, (uid, val) in enumerate(sorted_xp, start=1):
        try:
            user = await context.bot.get_chat_member(update.effective_chat.id, int(uid))
            name = user.user.first_name
        except Exception:
            name = "Unknown"
        board += f"🏅 {i}. {name} — {val} XP\n"
    await update.message.reply_text(board, parse_mode="Markdown")


# ---------------- VERIFY + WELCOME CARD ----------------
async def welcome_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    pv = pending_verifies.setdefault(chat_id, {})
    for member in update.message.new_chat_members:
        name = member.first_name or "User"
        try:
            card = make_welcome_card(name, theme="Movie")
            await update.message.reply_photo(photo=InputFile(card, filename="welcome.png"), caption=f"👋 Welcome {name}!")
        except Exception:
            pass
        kb = [[InlineKeyboardButton("✅ Verify", callback_data=f"verify_{member.id}")]]
        msg = await update.message.reply_text(f"👋 Welcome {name}! Please verify to chat.", reply_markup=InlineKeyboardMarkup(kb))
        try:
            await update.message.chat.restrict_member(member.id, ChatPermissions(can_send_messages=False))
        except Exception:
            pass
        pv[str(member.id)] = {"name": name, "msg_id": msg.message_id}
        save_store()

        # background task: after 120s remove if not verified
        async def _wait_and_kick(member_id, message_id, chat_obj, chat_id_str):
            await asyncio.sleep(120)
            pv2 = pending_verifies.get(chat_id_str, {})
            if str(member_id) in pv2:
                try:
                    await chat_obj.delete_message(message_id)
                    await chat_obj.kick_member(member_id)
                except Exception:
                    pass
                pv2.pop(str(member_id), None)
                save_store()

        # spawn background task
        asyncio.create_task(_wait_and_kick(member.id, msg.message_id, update.message.chat, chat_id))


async def verify_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split("_", 1)
    if len(parts) < 2:
        return await q.answer("Invalid verify data.", show_alert=True)
    uid = parts[1]
    chat = q.message.chat
    chat_id = str(chat.id)
    try:
        await chat.restrict_member(int(uid), ChatPermissions(can_send_messages=True))
        await q.edit_message_text("✅ Verification complete! You can chat now 🎉")
    except Exception:
        await q.answer("Verification failed. Ask admin.", show_alert=True)
    pv = pending_verifies.get(chat_id, {})
    pv.pop(uid, None)
    save_store()


# ---------------- ADMIN commands ----------------
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_chat, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to a user to ban.")
    user = update.message.reply_to_message.from_user
    try:
        await update.message.chat.ban_member(user.id)
    except Exception:
        pass
    await update.message.reply_text(f"🚫 {user.first_name} banned.")


async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_chat, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to a user to mute.")
    user = update.message.reply_to_message.from_user
    try:
        await update.message.chat.restrict_member(user.id, ChatPermissions(can_send_messages=False))
    except Exception:
        pass
    await update.message.reply_text(f"🔇 {user.first_name} muted.")


async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_chat, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to a user to warn.")
    user = update.message.reply_to_message.from_user
    uid = str(user.id)
    warns[uid] = warns.get(uid, 0) + 1
    save_store()
    if warns[uid] >= 3:
        try:
            await update.message.chat.ban_member(user.id)
        except Exception:
            pass
        warns[uid] = 0
        save_store()
        await update.message.reply_text(f"🚫 {user.first_name} auto-banned (3 warnings).")
    else:
        await update.message.reply_text(f"⚠️ {user.first_name} warned ({warns[uid]}/3).")


async def warnreset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_chat, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to reset warnings.")
    uid = str(update.message.reply_to_message.from_user.id)
    warns[uid] = 0
    save_store()
    await update.message.reply_text("✅ Warnings reset.")


async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_chat, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply kisi ko karke /promote likho.")
    user = update.message.reply_to_message.from_user
    try:
        await update.message.chat.promote_member(
            user.id,
            can_manage_chat=True,
            can_delete_messages=True,
            can_manage_video_chats=True,
            can_restrict_members=True,
            can_invite_users=True,
        )
        await update.message.reply_text(f"✅ {user.first_name} ko Admin bana diya gaya!")
    except Exception as e:
        await update.message.reply_text(f"❌ Promote failed: {e}")


async def demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_chat, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply kisi ko karke /demote likho.")
    user = update.message.reply_to_message.from_user
    try:
        # demote: promote_member with no rights will remove admin powers
        await update.message.chat.promote_member(user.id)
        await update.message.reply_text(f"❎ {user.first_name} se Admin permissions hata diya gaya!")
    except Exception as e:
        await update.message.reply_text(f"❌ Demote failed: {e}")


# Admin: manually verify (grant) payment
async def verify_payment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID and not await is_admin(update.effective_chat, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("Usage: /verify_payment <user_id> <days>")
    try:
        uid = int(args[0])
        days = int(args[1])
        set_premium(uid, days)
        await update.message.reply_text(f"✅ User {uid} granted premium for {days} days.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def reject_payment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID and not await is_admin(update.effective_chat, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /reject_payment <payment_ref>")
    ref = args[0]
    pp = data_store.get("pending_payments", {})
    if ref in pp:
        pp.pop(ref, None)
        save_store()
        await update.message.reply_text(f"❌ Payment {ref} rejected and removed from pending list.")
    else:
        await update.message.reply_text("Payment ref not found.")


# ---------------- TOOLS (pdf, convert existing) ----------------
async def pdf_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("✏️ Use: /pdf Your text here", parse_mode="Markdown")
    text = " ".join(context.args)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(190, 10, text)
    fname = f"text_{update.effective_user.id}.pdf"
    pdf.output(fname)
    link = upload_to_drive(fname, fname)
    await update.message.reply_text(f"📄 PDF Created!\n{link}", parse_mode="Markdown")
    try:
        os.remove(fname)
    except Exception:
        pass


USER_CONVERT = {}   # existing image convert
USER_TASKS = {}     # new: task state for a user (vid2aud, audconv, vcompress, vconvert)

async def set_convert_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("🖼️ Use: /convert png|jpeg|webp")
    fmt = context.args[0].lower()
    if fmt not in ["png", "jpeg", "webp"]:
        return await update.message.reply_text("⚠️ Only png/jpeg/webp allowed.")
    USER_CONVERT[update.effective_user.id] = fmt
    await update.message.reply_text(f"✅ Send me an image to convert to {fmt.upper()}")


async def sketch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_CONVERT[update.effective_user.id] = "sketch"
    await update.message.reply_text("✏️ Send me an image to make a pencil sketch!")


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # Check for pending payment screenshot (user sent a photo after /buy)
    # safe check - pending_payments_by_user may or may not be present
    if str(uid) in data_store.get("pending_payments_by_user", {}):
        pass

    if uid in USER_CONVERT:
        fmt = USER_CONVERT[uid]
        photo = update.message.photo[-1]
        f = await photo.get_file()
        path = f"image_{uid}.jpg"
        await f.download_to_drive(path)
        img = Image.open(path).convert("RGB")
        if fmt == "sketch":
            gray = img.convert("L")
            inverted = ImageOps.invert(gray)
            blur = inverted.filter(ImageFilter.GaussianBlur(8))
            sketch_img = Image.blend(gray, blur, 0.5)
            out = f"sketch_{uid}.jpg"
            sketch_img.save(out)
        else:
            out = f"converted_{uid}.{fmt}"
            img.save(out, fmt.upper())
        link = upload_to_drive(out, out)
        await update.message.reply_text(f"🖼️ Done!\n{link}", parse_mode="Markdown")
        try:
            os.remove(path)
            os.remove(out)
        except Exception:
            pass
        USER_CONVERT.pop(uid, None)
        return

    caption = update.message.caption or ""
    refs = re.findall(r"[A-F0-9\-]{6,}", caption)
    if refs:
        for ref in refs:
            pend = data_store.get("pending_payments", {}).get(ref)
            if pend and pend.get("user_id") == uid:
                await update.message.reply_text("Payment screenshot received. Admin will verify shortly. Ref: " + ref)
                path = f"payment_{ref}.jpg"
                photo = update.message.photo[-1]
                f = await photo.get_file()
                await f.download_to_drive(path)
                return

# ---------------- NEW: Video/Audio conversion commands ----------------
async def vid2aud_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_TASKS[update.effective_user.id] = {"task": "vid2aud"}
    await update.message.reply_text("📩 Send me a video file (as file/document or video) and I'll extract audio (MP3).")


async def audconv_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /audconv mp3|wav|m4a")
    fmt = context.args[0].lower()
    USER_TASKS[update.effective_user.id] = {"task": "audconv", "target": fmt}
    await update.message.reply_text(f"📩 Send me an audio file to convert to {fmt.upper()}.")


async def vcompress_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_TASKS[update.effective_user.id] = {"task": "vcompress"}
    await update.message.reply_text("📩 Send me a video file to compress (reasonable default).")


async def vconvert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /vconvert mp4|mkv|mov")
    fmt = context.args[0].lower()
    USER_TASKS[update.effective_user.id] = {"task": "vconvert", "target": fmt}
    await update.message.reply_text(f"📩 Send me a video file to convert to {fmt.upper()}.")


@ensure_user_limit
async def handle_media_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    task = USER_TASKS.get(uid)
    file_obj = None
    if update.message.document:
        file_obj = await update.message.document.get_file()
    elif update.message.video:
        file_obj = await update.message.video.get_file()
    elif update.message.audio:
        file_obj = await update.message.audio.get_file()
    elif update.message.voice:
        file_obj = await update.message.voice.get_file()
    else:
        await update.message.reply_text("Send a file (video/audio/document).")
        return

    tempdir = tempfile.mkdtemp()
    in_path = os.path.join(tempdir, "infile")
    # download
    try:
        await file_obj.download_to_drive(custom_path=in_path)
    except Exception:
        try:
            # fallback to download()
            await file_obj.download(custom_path=in_path)
        except Exception as e:
            await update.message.reply_text("Failed to download file: " + str(e))
            return

    try:
        if not task:
            await update.message.reply_text("No task selected. Use /vid2aud or /audconv or /vcompress or /vconvert first.")
            return

        tname = task.get("task")
        if tname == "vid2aud":
            out_path = os.path.join(tempdir, "out.mp3")
            cmd = [FFMPEG_PATH, "-i", in_path, "-vn", "-acodec", "libmp3lame", "-ab", "192k", out_path]
            subprocess.run(cmd, check=False)
            await update.message.reply_audio(audio=open(out_path, "rb"))
        elif tname == "audconv":
            target = task.get("target", "mp3")
            out_path = os.path.join(tempdir, f"out.{target}")
            cmd = [FFMPEG_PATH, "-i", in_path, out_path]
            subprocess.run(cmd, check=False)
            await update.message.reply_document(document=open(out_path, "rb"))
        elif tname == "vcompress":
            out_path = os.path.join(tempdir, "out.mp4")
            cmd = [FFMPEG_PATH, "-i", in_path, "-vcodec", "libx264", "-crf", "28", "-preset", "veryfast", out_path]
            subprocess.run(cmd, check=False)
            await update.message.reply_document(document=open(out_path, "rb"))
        elif tname == "vconvert":
            target = task.get("target", "mp4")
            out_path = os.path.join(tempdir, f"out.{target}")
            cmd = [FFMPEG_PATH, "-i", in_path, out_path]
            subprocess.run(cmd, check=False)
            await update.message.reply_document(document=open(out_path, "rb"))
        else:
            await update.message.reply_text("Unknown task.")
    except Exception as e:
        await update.message.reply_text("Processing failed: " + str(e))
    finally:
        USER_TASKS.pop(uid, None)
        try:
            for f in os.listdir(tempdir):
                try:
                    os.remove(os.path.join(tempdir, f))
                except Exception:
                    pass
            os.rmdir(tempdir)
        except Exception:
            pass


# ---------------- BUY flow (Option B UPI screenshot) ----------------
async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ref = uuid.uuid4().hex[:10].upper()
    data_store.setdefault("pending_payments", {})[ref] = {
        "user_id": uid,
        "ts": datetime.datetime.utcnow().isoformat(),
        "note": "UPI payment pending",
        "amounts": {"1": 10, "7": 50, "30": 100},
    }
    save_store()
    txt = (
        f"🔔 Payment Instructions (Manual UPI)\n\n"
        f"1) Transfer via UPI to: {UPI_ID}\n"
        f"2) In UPI note/remark, add this reference: {ref}\n"
        f"3) After payment, send a screenshot of the successful payment here with caption containing the reference {ref}.\n\n"
        "⚠️ After you send the screenshot, an admin will verify and grant premium manually.\n\n"
        "Plans\n• 1 day — ₹10\n• 7 days — ₹50\n• 30 days — ₹100\n\n"
        "Admin verification command (for admins): /verify_payment <user_id> <days>\n"
    )
    await update.message.reply_text(txt, parse_mode="Markdown")


# ---------------- ADMIN UTIL: list pending ----------------
async def list_pending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID and not await is_admin(update.effective_chat, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    pp = data_store.get("pending_payments", {})
    if not pp:
        return await update.message.reply_text("No pending payments.")
    lines = []
    for ref, info in pp.items():
        lines.append(f"{ref} — user:{info.get('user_id')} — ts:{info.get('ts')}")
    await update.message.reply_text("Pending:\n" + "\n".join(lines))


# ---------------- CLEAN / GROUPSTATS / VERIFYLIST ----------------
async def clean_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_chat, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    chat = update.effective_chat
    removed = 0
    try:
        admins = await chat.get_administrators()
    except Exception:
        admins = []
    for admin in admins:
        if admin.user.is_deleted:
            try:
                await chat.ban_member(admin.user.id)
                await chat.unban_member(admin.user.id)
                removed += 1
            except Exception:
                pass
    chat_id = str(chat.id)
    pv = pending_verifies.get(chat_id, {})
    to_remove = [uid for uid, info in pv.items() if info.get("name") == "Deleted"]
    for uid in to_remove:
        pv.pop(uid, None)
        removed += 1
    save_store()
    await update.message.reply_text(f"🧹 Cleaned {removed} deleted/pending accounts.")


async def groupstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    try:
        total = await context.bot.get_chat_member_count(chat.id)
    except Exception:
        total = "Unknown"
    try:
        admins = await chat.get_administrators()
    except Exception:
        admins = []
    pending = len(pending_verifies.get(str(chat.id), {}))
    await update.message.reply_text(f"📊 Group Stats:\n👥 Members: {total}\n🛡️ Admins: {len(admins)}\n🕒 Pending Verify: {pending}")


async def verifylist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    pv = pending_verifies.get(chat_id, {})
    if not pv:
        return await update.message.reply_text("✅ No pending verifications.")
    text = h("Pending Verifications") + "\n".join([f"• {i.get('name')}" for i in pv.values()])
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------- FUN (kept) ----------------
async def joke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    JOKES = [
        "😂 टीचर: बच्चों बताओ, सबसे पुरानी दीवार कौन सी है? छात्र: Facebook की वॉल!",
        "🤣 पप्पू: मुझे शादी करनी है! दोस्त: क्यों? पप्पू: घर में WiFi नहीं है!",
        "😅 डॉक्टर: आंख कैसे लगी? मरीज: बीवी से लड़ाई हुई!",
        "😂 मास्टरजी: बिजली कहाँ से आती है? बच्चा: पड़ोसी के घर से!",
    ]
    await update.message.reply_text(random.choice(JOKES))


async def love(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = " ".join(context.args) if context.args else "someone"
    await update.message.reply_text(f"❤️ {update.effective_user.first_name} + {name} = {random.randint(0,100)}% प्यार 💞")


async def roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🎲 You rolled {random.randint(1, 6)}!")


# ---------------- MAIN ----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Core
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))

    # Verify system
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_verify))
    app.add_handler(CallbackQueryHandler(verify_user, pattern=r"verify_\d+"))

    # Menu
    app.add_handler(CallbackQueryHandler(menu_buttons))

    # Security
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anti_link))

    # Fun
    app.add_handler(CommandHandler("joke", joke))
    app.add_handler(CommandHandler("love", love))
    app.add_handler(CommandHandler("roll", roll))

    # Tools
    app.add_handler(CommandHandler("pdf", pdf_cmd))
    app.add_handler(CommandHandler("convert", set_convert_format))
    app.add_handler(CommandHandler("sketch", sketch))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))

    # New media tasks
    app.add_handler(CommandHandler("vid2aud", vid2aud_cmd))
    app.add_handler(CommandHandler("audconv", audconv_cmd))
    app.add_handler(CommandHandler("vcompress", vcompress_cmd))
    app.add_handler(CommandHandler("vconvert", vconvert_cmd))
    app.add_handler(MessageHandler((filters.Document | filters.VIDEO | filters.AUDIO | filters.VOICE) & ~filters.COMMAND, handle_media_file))

    # Buy / Payment flow
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("verify_payment", verify_payment_cmd))   # admin
    app.add_handler(CommandHandler("reject_payment", reject_payment_cmd))   # admin
    app.add_handler(CommandHandler("pending_list", list_pending_cmd))       # admin

    # XP
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    # give_xp handler should be last for text to avoid conflicts, but we keep anti_link earlier.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, give_xp))

    # Admin
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("warnreset", warnreset))
    app.add_handler(CommandHandler("promote", promote))
    app.add_handler(CommandHandler("demote", demote))
    app.add_handler(CommandHandler("clean", clean_cmd))
    app.add_handler(CommandHandler("groupstats", groupstats))
    app.add_handler(CommandHandler("verifylist", verifylist))

    print("🌹 XenRose Bot v9.0 Ultra is LIVE — Stable GSMHost + Manual UPI payment enabled 💫")
    app.run_polling()


if __name__ == "__main__":
    main()
