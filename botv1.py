import logging
import hashlib
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, CallbackQueryHandler, filters
)
from collections import defaultdict, Counter

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# ========== Config ==========
ADMIN_ID = 7174319975
ALLOWED_USERS = set([ADMIN_ID])

# ========== Predictor nâng cao ==========
history = []
rule_stats = {}

def predictor_basic(md5): return int(md5[0], 16) % 2
def predictor_parity(md5): return sum(int(c, 16) for c in md5 if c.isdigit()) % 2
def predictor_tail(md5): return int(md5[-1], 16) % 2
def predictor_trend(md5): return 1 if len(history) < 3 else int(sum(history[-3:]) >= 2)

def predictor_ngram_multi(md5):
    if len(history) < 5: return 1
    score, count = 0, 0
    for n in range(2, 5):
        if len(history) < n + 1: continue
        pattern = tuple(history)[-n:]
        total = match = 0
        for i in range(len(history) - n):
            if tuple(history[i:i+n]) == pattern:
                total += 1
                if history[i+n] == 1:
                    match += 1
        if total > 0:
            score += match / total
            count += 1
    return 1 if count == 0 or (score / count) > 0.5 else 0

predictors = {
    'basic': predictor_basic,
    'parity': predictor_parity,
    'tail': predictor_tail,
    'trend': predictor_trend,
    'ngram_multi': predictor_ngram_multi,
    'md5_hex_entropy_score': lambda md5: (lambda freq: 0 if (-sum((count / 32) * math.log2(count / 32) for count in freq.values()) < 3.4 and max(freq.values()) >= 5) else 1)(Counter(md5)),
    'last_k_winrate': lambda md5: 1 if len(history) < 6 or sum(history[-6:]) / 6 >= 0.5 else 0,
    'md5_pair_symmetry': lambda md5: 0 if sum(1 for i in range(len(md5)//2) if md5[i] == md5[-(i+1)]) < 6 else 1,
    'repeated_digit_bias': lambda md5: 0 if any(v >= 4 for v in Counter(c for c in md5 if c.isdigit()).values()) else 1,
    'odd_digit_ratio': lambda md5: (lambda digits: 1 if digits and sum(1 for d in digits if d % 2 == 1) / len(digits) >= 0.5 else 0)([int(c) for c in md5 if c.isdigit()]),
}

predictor_stats = {name: {'correct': 1, 'total': 2, 'disabled': False} for name in predictors}
last_md5 = {}

def mine_rule():
    if len(history) < 6: return
    for size in range(3, 6):
        pattern = tuple(history)[-size:]
        matched_indices = [i for i in range(len(history) - size - 1) if tuple(history[i:i+size]) == pattern]
        for i in matched_indices:
            next_result = history[i + size]
            key = tuple(pattern)
            stat = rule_stats.setdefault(key, {'match': 0, 'total': 0, 'result': next_result})
            stat['total'] += 1
            if stat['result'] == next_result:
                stat['match'] += 1
            break

def apply_rules():
    for size in range(5, 2, -1):
        pattern = tuple(history)[-size:]
        stat = rule_stats.get(pattern)
        if stat and stat['total'] >= 3 and stat['match'] / stat['total'] >= 0.7:
            return stat['result']
    return None

def auto_disable_predictors():
    for name, stat in predictor_stats.items():
        if stat['total'] >= 20:
            acc = stat['correct'] / stat['total']
            if acc < 0.6:
                stat['disabled'] = True
            elif acc >= 0.65 and stat.get('disabled'):
                stat['disabled'] = False

def ensemble_predict(md5):
    votes = {}
    weights = {}
    for name, func in predictors.items():
        stat = predictor_stats[name]
        if stat['disabled']: continue
        try:
            votes[name] = func(md5)
            acc = stat['correct'] / stat['total']
            weights[name] = acc
        except:
            continue
    total_score = {0: 0, 1: 0}
    for name, vote in votes.items():
        acc = weights.get(name, 0.5)
        weight = 0.3 if acc < 0.6 else 1.0 if acc > 0.8 else acc
        total_score[vote] += weight
    final = max(total_score, key=total_score.get)
    confidence = 100 * total_score[final] / (sum(total_score.values()) + 1e-6)
    top3 = sorted(weights, key=weights.get, reverse=True)[:3]
    return final, confidence, top3, votes

# ========== Telegram Handlers ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔮 Gửi mã MD5 để bot dự đoán Tài (1) / Xỉu (0). Gửi 0 hoặc 1 để xác nhận kết quả thực tế.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message.text.strip().lower()

    if user_id not in ALLOWED_USERS:
        await update.message.reply_text("❌ Bạn không có quyền sử dụng bot này.")
        return

    if msg in ['0', '1']:
        if user_id not in last_md5:
            await update.message.reply_text("⚠️ Bạn chưa gửi mã MD5 để dự đoán.")
            return
        feedback = int(msg)
        history.append(feedback)
        mine_rule()
        md5 = last_md5[user_id]
        _, _, _, detail = ensemble_predict(md5)
        for name, pred in detail.items():
            predictor_stats[name]['total'] += 1
            if pred == feedback:
                predictor_stats[name]['correct'] += 1
        auto_disable_predictors()
        await update.message.reply_text(f"✅ Ghi nhận kết quả: {'Tài' if feedback else 'Xỉu'}")
        return

    if len(msg) != 32 or not all(c in '0123456789abcdef' for c in msg):
        await update.message.reply_text("❌ Vui lòng gửi chuỗi MD5 hợp lệ (32 ký tự hex).")
        return

    md5 = msg
    last_md5[user_id] = md5
    rule_result = apply_rules()
    result, confidence, top3, detail = ensemble_predict(md5)
    final = rule_result if rule_result is not None else result

    reply = f"👉 <b>Dự đoán:</b> <b>{'Tài' if final else 'Xỉu'}</b> (🎯 {confidence:.1f}%)\n"
    reply += f"📊 <b>Top 3 predictor:</b> {', '.join(top3)}\n"
    for name in top3:
        pred = detail[name]
        reply += f"  - {name}: {'Tài' if pred else 'Xỉu'}\n"
    if rule_result is not None:
        reply += f"\n📘 <b>Rule-based override:</b> {'Tài' if rule_result else 'Xỉu'}"

    await update.message.reply_text(reply, parse_mode='HTML')

# ========== Menu cho Admin ==========
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ Bạn không phải admin.")
    keyboard = [
        [InlineKeyboardButton("📈 Thống kê", callback_data='stats')],
        [InlineKeyboardButton("👥 Danh sách user", callback_data='users')],
        [InlineKeyboardButton("➕ Thêm user", callback_data='add')],
        [InlineKeyboardButton("🗑️ Xoá user", callback_data='remove')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🔧 Menu quản trị:", reply_markup=reply_markup)

async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cmd = query.data
    if cmd == 'stats':
        await stats(update, context)
    elif cmd == 'users':
        await list_users(update, context)
    elif cmd == 'add':
        await query.edit_message_text("Gửi lệnh /add <user_id> để thêm user.")
    elif cmd == 'remove':
        await query.edit_message_text("Gửi lệnh /remove <user_id> để xoá user.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["📈 Thống kê độ chính xác:"]
    for name, stat in predictor_stats.items():
        acc = 100 * stat['correct'] / stat['total']
        status = "✅" if not stat.get('disabled') else "❌ (disabled)"
        lines.append(f"{status} {name}: {stat['correct']}/{stat['total']} = {acc:.1f}%")
    await update.message.reply_text('\n'.join(lines))

# ========== Admin Commands ==========
async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args: return await update.message.reply_text("❗ /add <user_id>")
    uid = int(context.args[0])
    ALLOWED_USERS.add(uid)
    await update.message.reply_text(f"✅ Đã thêm user {uid}")

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args: return await update.message.reply_text("❗ /remove <user_id>")
    uid = int(context.args[0])
    ALLOWED_USERS.discard(uid)
    await update.message.reply_text(f"🗑️ Đã xoá user {uid}")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    users = "\n".join(str(u) for u in ALLOWED_USERS)
    await update.message.reply_text(f"👥 Danh sách user được phép:\n{users}")

# ========== Bot Setup ==========
if __name__ == '__main__':
    app = ApplicationBuilder().token("8092431132:AAHXIYr6oZk-9x_e6wUOoqz6Iov7LAm-7f0").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", admin_menu))
    app.add_handler(CommandHandler("add", add_user))
    app.add_handler(CommandHandler("remove", remove_user))
    app.add_handler(CommandHandler("list", list_users))

    app.add_handler(CallbackQueryHandler(handle_menu_callback))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("🤖 Bot đang chạy...")
    app.run_polling()