import discord
from discord import app_commands
import aiohttp
import asyncio
import json
import random
import re
import base64
from datetime import datetime, timezone

API_BASE = "https://discord.com/api/v9"
POLL_INTERVAL = 60
HEARTBEAT_INTERVAL = 20
AUTO_ACCEPT = True

SUPPORTED_TASKS = [
    "WATCH_VIDEO",
    "PLAY_ON_DESKTOP",
    "STREAM_ON_DESKTOP",
    "PLAY_ACTIVITY",
    "WATCH_VIDEO_ON_MOBILE",
]

active_sessions = {}

def make_progress_bar(percent, length=15):
    filled = int(round(length * percent / 100))
    bar = '▰' * filled + '▱' * (length - filled)
    return f"`{bar}` **{percent:.1f}%**"

def create_scan_embed(user):
    embed = discord.Embed(title="🛰️ Đang thiết lập kết nối...", color=0x2b2d31)
    embed.description = f"> Xin chào **{user.display_name}**!\n> Hệ thống đang đồng bộ và phân tích dữ liệu...\n\n⚡ Quá trình này sẽ diễn ra trong vài giây."
    if user.display_avatar:
        embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Xoài Xanh • Đang xử lý")
    return embed

def create_list_embed(quests):
    completed = sum(1 for q in quests if is_completed(q))
    todo = sum(1 for q in quests if is_completable(q) and not is_completed(q))
    expired = len(quests) - completed - todo
    
    desc = f"> Hệ thống ghi nhận tổng cộng **{len(quests)}** nhiệm vụ.\n"
    desc += f"> 🟢 Hoàn thành: **{completed}** |  ⏳ Cần chạy: **{todo}** |  🔴 Bỏ qua: **{expired}**\n\n"
    
    for q in quests:
        name = get_quest_name(q)
        task = get_task_type(q) or "UNKNOWN"
        needed = get_seconds_needed(q)
        mins = needed // 60
        
        if is_completed(q):
            icon = "✅"
            status = "Hoàn tất"
        elif not is_completable(q):
            icon = "⚠️"
            status = "Không khả dụng"
        else:
            icon = "⏳" 
            done = get_seconds_done(q)
            pct = int((done / needed) * 100) if needed > 0 else 0
            status = f"Tiến độ: {pct}%"
            
        desc += f"{icon} **{name}**\n└ 🏷️ `{task}` • ⏱️ {mins}m • {status}\n\n"
        
    if len(desc) > 4096:
        desc = desc[:4000] + "\n... (Danh sách được thu gọn)"
        
    embed = discord.Embed(title="📊 Bảng Phân Bổ Nhiệm Vụ", description=desc, color=0x2b2d31)
    embed.set_footer(text=f"Database đã đồng bộ | {completed}/{len(quests)} hoàn tất")
    return embed

def create_start_embed(name, task_type, seconds_needed):
    embed = discord.Embed(title=f"🚀 Khởi động: {name}", color=0x2b2d31)
    embed.add_field(name="🎮 Thể loại", value=f"`{task_type}`", inline=True)
    embed.add_field(name="⏱️ Thời lượng", value=f"`{seconds_needed // 60}m {seconds_needed % 60}s`", inline=True)
    embed.add_field(name="", value=make_progress_bar(0.0), inline=False)
    embed.set_footer(text="Xoài Xanh • Bắt đầu xử lý")
    return embed

def create_progress_embed(name, seconds_done, seconds_needed):
    percent = min(100.0, (seconds_done / seconds_needed) * 100) if seconds_needed > 0 else 100.0
    remaining = max(0, seconds_needed - seconds_done)
    
    embed = discord.Embed(title=f"⚡ Đang chạy: {name}", color=0x2b2d31)
    embed.description = f"{make_progress_bar(percent)}\n\n> 🎯 **Tiến độ:** `{int(seconds_done)} / {seconds_needed}s`\n> ⏳ **Còn lại:** `~{remaining // 60:.1f} phút`"
    embed.set_footer(text="Xoài Xanh • Đang đồng bộ tiến trình")
    return embed

def create_complete_embed(name, task_type):
    embed = discord.Embed(title="🎉 Nhiệm Vụ Hoàn Tất!", color=0x57F287)
    embed.description = f"> **{name}**\n> 🏷️ Phân loại: `{task_type}`\n\n💎 Phần thưởng đã sẵn sàng để nhận trên ứng dụng Discord!"
    embed.set_footer(text="Xoài Xanh • Thành công")
    return embed

def create_early_exit_embed(user, quests):
    total = len(quests)
    completed = sum(1 for q in quests if is_completed(q))
    expired = total - completed
    
    embed = discord.Embed(title="🛡️ BÁO CÁO TỔNG KẾT CHI TIẾT", color=0x9B59B6)
    desc = f"> Xin chào **{user.display_name}**, tất cả quest đã được hoàn thành từ trước!\n\n"
    desc += f"> ✅ **{completed}/{total}** quest đã xong\n"
    desc += f"> ⚠️ **{expired}** quest hết hạn hoặc không hỗ trợ\n\n"
    desc += "Không có nhiệm vụ nào cần xử lý thêm trong phiên này.\n\n"
    desc += "🔎 **KẾT QUẢ QUÉT**\n"
    desc += f"```text\nTổng số Quest:    {total}\nĐã hoàn thành:    {completed}\nHết hạn:          {expired}\nCần làm lần này:  0\n```\n"
    desc += "🔐 **BẢO MẬT HỆ THỐNG**\n> Token của bạn đã được **xóa hoàn toàn** khỏi bộ nhớ."
    
    embed.description = desc
    if user.display_avatar:
        embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Xoài Xanh • Hoạt động an toàn")
    return embed

def create_final_summary_embed(user, successes, todo_initial):
    embed = discord.Embed(title="🏆 Báo Cáo Tổng Kết Phiên", color=0xFEE75C)
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url if user.display_avatar else None)
    
    desc = f"> ⚡ **Hệ thống đã tự động giải quyết ({len(successes)}/{todo_initial} thành công)**\n\n"
    for name in successes:
        desc += f"✅ **{name}**\n"
        
    if not successes:
        desc += "Phân tích không tìm thấy nhiệm vụ khả dụng nào mới để thực hiện."
        
    embed.description = desc
    embed.set_footer(text=f"User ID: {user.id} • Hoạt động hoàn tất")
    return embed

async def fetch_latest_build_number():
    fallback = 504649
    try:
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        async with aiohttp.ClientSession() as session:
            async with session.get("https://discord.com/app", headers={"User-Agent": ua}, timeout=15) as r:
                if r.status != 200: return fallback
                text = await r.text()
                scripts = re.findall(r'/assets/([a-f0-9]+)\.js', text)
                if not scripts:
                    scripts_alt = re.findall(r'src="(/assets/[^"]+\.js)"', text)
                    scripts = [s.split('/')[-1].replace('.js', '') for s in scripts_alt]
                if not scripts: return fallback
                for asset_hash in scripts[-5:]:
                    try:
                        async with session.get(f"https://discord.com/assets/{asset_hash}.js", headers={"User-Agent": ua}, timeout=15) as ar:
                            ar_text = await ar.text()
                            m = re.search(r'buildNumber["\s:]+["\s]*(\d{5,7})', ar_text)
                            if m: return int(m.group(1))
                    except Exception: continue
        return fallback
    except Exception:
        return fallback

def make_super_properties(build_number):
    obj = {
        "os": "Windows", "browser": "Discord Client", "release_channel": "stable",
        "client_version": "1.0.9175", "os_version": "10.0.26100", "os_arch": "x64", "app_arch": "x64",
        "system_locale": "en-US",
        "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9175 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36",
        "browser_version": "32.2.7", "client_build_number": build_number, "native_build_number": 59498, "client_event_source": None,
    }
    return base64.b64encode(json.dumps(obj).encode()).decode()

class DiscordAPI:
    def __init__(self, token, build_number):
        self.token = token
        self.build_number = build_number
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9175 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36"
        sp = make_super_properties(build_number)
        self.headers = {
            "Authorization": token, "Content-Type": "application/json", "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9", "User-Agent": ua, "X-Super-Properties": sp,
            "X-Discord-Locale": "en-US", "X-Discord-Timezone": "Asia/Ho_Chi_Minh",
            "Origin": "https://discord.com", "Referer": "https://discord.com/channels/@me",
        }
        self.session = aiohttp.ClientSession(headers=self.headers)

    async def get(self, path): return await self.session.get(f"{API_BASE}{path}")
    async def post(self, path, payload=None): return await self.session.post(f"{API_BASE}{path}", json=payload)
    async def validate_token(self):
        try:
            async with await self.get("/users/@me") as r: return r.status == 200
        except Exception: return False
    async def close(self): await self.session.close()

def _get(d, *keys):
    if d is None: return None
    for k in keys:
        if k in d: return d[k]
    return None

def get_task_config(quest): return _get(quest.get("config", {}), "taskConfig", "task_config", "taskConfigV2", "task_config_v2")

def get_quest_name(quest):
    cfg = quest.get("config", {})
    msgs = cfg.get("messages", {})
    name = _get(msgs, "questName", "quest_name")
    if name: return name.strip()
    game = _get(msgs, "gameTitle", "game_title")
    if game: return game.strip()
    return cfg.get("application", {}).get("name") or f"Quest#{quest.get('id', '?')}"

def get_expires_at(quest): return _get(quest.get("config", {}), "expiresAt", "expires_at")

def get_user_status(quest):
    us = _get(quest, "userStatus", "user_status")
    return us if isinstance(us, dict) else {}

def is_completable(quest):
    expires = get_expires_at(quest)
    if expires:
        try:
            exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if exp_dt <= datetime.now(timezone.utc): return False
        except Exception: pass
    tc = get_task_config(quest)
    if not tc or "tasks" not in tc: return False
    return any(tc["tasks"].get(t) is not None for t in SUPPORTED_TASKS)

def is_enrolled(quest): return bool(_get(get_user_status(quest), "enrolledAt", "enrolled_at"))
def is_completed(quest): return bool(_get(get_user_status(quest), "completedAt", "completed_at"))

def get_task_type(quest):
    tc = get_task_config(quest)
    if not tc or "tasks" not in tc: return None
    for t in SUPPORTED_TASKS:
        if tc["tasks"].get(t) is not None: return t
    return None

def get_seconds_needed(quest):
    tc = get_task_config(quest)
    task_type = get_task_type(quest)
    return tc["tasks"][task_type].get("target", 0) if tc and task_type else 0

def get_seconds_done(quest):
    task_type = get_task_type(quest)
    if not task_type: return 0
    progress = get_user_status(quest).get("progress", {})
    return progress.get(task_type, {}).get("value", 0) if progress else 0

class QuestAutocompleter:
    def __init__(self, api, interaction):
        self.api = api
        self.interaction = interaction
        self.user = interaction.user
        self.completed_ids = set()
        self.session_successes = []
        self.todo_initial = 0
        self.running = True

    async def send_dm(self, embed):
        try:
            return await self.user.send(embed=embed)
        except discord.Forbidden:
            return None

    async def fetch_quests(self):
        try:
            async with await self.api.get("/quests/@me") as r:
                if r.status == 200:
                    data = await r.json()
                    if isinstance(data, dict): return data.get("quests", [])
                    elif isinstance(data, list): return data
                    return []
                elif r.status == 429:
                    retry_after = (await r.json()).get("retry_after", 10)
                    await asyncio.sleep(retry_after)
                    return await self.fetch_quests()
                return []
        except Exception: return []

    async def enroll_quest(self, quest):
        qid = quest["id"]
        for _ in range(3):
            if not self.running: return False
            try:
                payload = {
                    "location": 11, "is_targeted": False, "metadata_raw": None, "metadata_sealed": None,
                    "traffic_metadata_raw": quest.get("traffic_metadata_raw"),
                    "traffic_metadata_sealed": quest.get("traffic_metadata_sealed"),
                }
                async with await self.api.post(f"/quests/{qid}/enroll", payload) as r:
                    if r.status == 429:
                        await asyncio.sleep((await r.json()).get("retry_after", 5) + 1)
                        continue
                    if r.status in (200, 201, 204): return True
                    return False
            except Exception: return False
        return False

    async def auto_accept(self, quests):
        if not AUTO_ACCEPT: return quests
        unaccepted = [q for q in quests if not is_enrolled(q) and not is_completed(q) and is_completable(q)]
        for q in unaccepted:
            if not self.running: break
            await self.enroll_quest(q)
            await asyncio.sleep(3)
        await asyncio.sleep(2)
        return await self.fetch_quests()

    async def track_progress(self, quest, task_type, payload_builder, endpoint, interval):
        name = get_quest_name(quest)
        qid = quest["id"]
        seconds_needed = get_seconds_needed(quest)
        seconds_done = get_seconds_done(quest)
        
        msg = await self.send_dm(create_start_embed(name, task_type, seconds_needed))
        last_update_val = seconds_done

        while seconds_done < seconds_needed and self.running:
            try:
                payload = payload_builder(seconds_done, seconds_needed)
                async with await self.api.post(f"/quests/{qid}/{endpoint}", payload) as r:
                    if r.status == 200:
                        body = await r.json()
                        if endpoint == "video-progress":
                            if body.get("completed_at"): break
                            seconds_done = min(seconds_needed, payload["timestamp"])
                        else: 
                            progress_data = body.get("progress", {})
                            if progress_data and task_type in progress_data:
                                seconds_done = progress_data[task_type].get("value", seconds_done)
                            if body.get("completed_at") or seconds_done >= seconds_needed: break
                        
                        if msg and int(seconds_done) > int(last_update_val):
                            await msg.edit(embed=create_progress_embed(name, seconds_done, seconds_needed))
                            last_update_val = seconds_done
                            
                    elif r.status == 429:
                        await asyncio.sleep((await r.json()).get("retry_after", 5) + 1)
                        continue
            except Exception: pass
            await asyncio.sleep(interval)

        try:
            terminal_payload = payload_builder(seconds_needed, seconds_needed)
            if endpoint == "heartbeat": terminal_payload["terminal"] = True
            await self.api.post(f"/quests/{qid}/{endpoint}", terminal_payload)
        except Exception: pass
        
        if msg:
            await msg.edit(embed=create_complete_embed(name, task_type))
        else:
            await self.send_dm(create_complete_embed(name, task_type))
            
        self.session_successes.append(name)

    async def complete_video(self, quest):
        def build_payload(done, needed):
            target_ts = min(needed, done + 7 + random.random())
            return {"timestamp": target_ts}
        await self.track_progress(quest, get_task_type(quest), build_payload, "video-progress", 1)

    async def complete_heartbeat(self, quest):
        pid = random.randint(1000, 30000)
        def build_payload(done, needed):
            return {"stream_key": f"call:0:{pid}", "terminal": False}
        await self.track_progress(quest, get_task_type(quest), build_payload, "heartbeat", HEARTBEAT_INTERVAL)

    async def complete_activity(self, quest):
        def build_payload(done, needed):
            return {"stream_key": "call:0:1", "terminal": False}
        await self.track_progress(quest, "PLAY_ACTIVITY", build_payload, "heartbeat", HEARTBEAT_INTERVAL)

    async def process_quest(self, quest):
        qid = quest.get("id")
        task_type = get_task_type(quest)
        if not task_type or qid in self.completed_ids: return
        
        if task_type in ("WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE"):
            await self.complete_video(quest)
        elif task_type in ("PLAY_ON_DESKTOP", "STREAM_ON_DESKTOP"):
            await self.complete_heartbeat(quest)
        elif task_type == "PLAY_ACTIVITY":
            await self.complete_activity(quest)
            
        self.completed_ids.add(qid)

    async def run(self):
        await self.send_dm(create_scan_embed(self.user))
        quests = await self.fetch_quests()
        
        if not quests:
            await self.send_dm(discord.Embed(title="❌ Lỗi Hệ Thống", description="> Không tìm thấy nhiệm vụ nào khả dụng hoặc token đã hết hạn.", color=discord.Color.red()))
            self.running = False
            return
            
        self.todo_initial = sum(1 for q in quests if is_completable(q) and not is_completed(q))
        
        if self.todo_initial == 0:
            await self.send_dm(create_early_exit_embed(self.user, quests))
            self.running = False
            await self.api.close()
            if self.user.id in active_sessions:
                del active_sessions[self.user.id]
            return
            
        await self.send_dm(create_list_embed(quests))
        quests = await self.auto_accept(quests)
        
        while self.running:
            quests = await self.fetch_quests()
            if not quests: break
            
            actionable = [q for q in quests if is_enrolled(q) and not is_completed(q) and is_completable(q) and q.get("id") not in self.completed_ids]
            
            if not actionable:
                break
                
            for q in actionable:
                if not self.running: break
                await self.process_quest(q)
                
        if self.running:
            final_embed = create_final_summary_embed(self.user, self.session_successes, self.todo_initial)
            try:
                await self.interaction.channel.send(embed=final_embed)
            except discord.Forbidden:
                await self.send_dm(final_embed)
                
        self.running = False
        await self.api.close()
        if self.user.id in active_sessions:
            del active_sessions[self.user.id]

class TermsView(discord.ui.View):
    def __init__(self, token, user):
        super().__init__(timeout=120)
        self.token = token
        self.user = user

    @discord.ui.button(label="Đồng ý điều khoản", style=discord.ButtonStyle.success)
    async def agree(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("Bạn không có quyền tương tác với bảng này.", ephemeral=True)
            
        for child in self.children:
            child.disabled = True
            
        embed = discord.Embed(title="✅ Xác Nhận Thành Công", color=0x2b2d31)
        embed.description = "> Chấp thuận các điều khoản an toàn hệ thống.\n\n🛡️ **Khởi chạy tiến trình background...**\n💬 Bạn có thể theo dõi chi tiết qua Tin nhắn riêng (DM)!"
        await interaction.response.edit_message(embed=embed, view=self)
        
        build_number = await fetch_latest_build_number()
        api = DiscordAPI(self.token, build_number)
        
        is_valid = await api.validate_token()
        if not is_valid:
            await api.close()
            await interaction.followup.send("⚠️ Token cung cấp không hợp lệ hoặc kết nối bị từ chối.", ephemeral=True)
            return

        completer = QuestAutocompleter(api, interaction)
        task = asyncio.create_task(completer.run())
        
        active_sessions[interaction.user.id] = {
            "task": task,
            "completer": completer,
            "api": api
        }

    @discord.ui.button(label="Từ chối", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("Bạn không có quyền tương tác với bảng này.", ephemeral=True)
            
        for child in self.children:
            child.disabled = True
            
        embed = discord.Embed(title="❌ Hủy Yêu Cầu", color=discord.Color.red())
        embed.description = "> Yêu cầu đã bị từ chối. Tiến trình bị hủy bỏ."
        await interaction.response.edit_message(embed=embed, view=self)

class QuestBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

bot = QuestBot()

@bot.tree.command(name="quest", description="Cấp quyền token để tự động xử lý Discord Quests")
@app_commands.describe(token="Nhập Discord Token cá nhân")
async def cmd_quest(interaction: discord.Interaction, token: str):
    if interaction.user.id in active_sessions:
        await interaction.response.send_message("⚠️ Một tiến trình khác đang hoạt động. Vui lòng gõ `/cancel` trước khi bắt đầu phiên mới.", ephemeral=True)
        return

    embed = discord.Embed(title="🛡️ Cảnh Báo An Toàn Hệ Thống", color=0x2b2d31)
    embed.description = "> Việc cung cấp Token cá nhân chứa đựng những rủi ro bảo mật nhất định.\n> Hãy đảm bảo bạn hiểu rõ cơ chế trước khi xác nhận tiến hành."
    view = TermsView(token, interaction.user)
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

@bot.tree.command(name="cancel", description="Đóng băng và hủy bỏ tiến trình hiện tại")
async def cmd_cancel(interaction: discord.Interaction):
    if interaction.user.id not in active_sessions:
        await interaction.response.send_message("Không tìm thấy tiến trình nào đang chạy trong bộ nhớ.", ephemeral=True)
        return

    session = active_sessions[interaction.user.id]
    session["completer"].running = False
    session["task"].cancel()
    await session["api"].close()
    
    del active_sessions[interaction.user.id]
    await interaction.response.send_message("🛑 **Tiến trình đã được ngắt kết nối an toàn.**", ephemeral=True)

@bot.tree.command(name="status", description="Truy xuất trạng thái phiên chạy")
async def cmd_status(interaction: discord.Interaction):
    if interaction.user.id not in active_sessions:
        await interaction.response.send_message("Hệ thống đang rảnh. Hãy dùng `/quest` để tạo phiên.", ephemeral=True)
        return

    completer = active_sessions[interaction.user.id]["completer"]
    completed_count = len(completer.completed_ids)
    
    await interaction.response.send_message(f"📊 **Báo cáo nhanh:** Hệ thống đã hoàn tất `{completed_count}` nhiệm vụ trong phiên này.", ephemeral=True)

if __name__ == "__main__":
    import os
    # Đọc giá trị từ biến môi trường trên Render có tên là YOUR_BOT_TOKEN_HERE
    TOKEN = os.getenv("YOUR_BOT_TOKEN_HERE")
    
    if TOKEN is None:
        print("Lỗi: Không tìm thấy Token! Vui lòng kiểm tra lại Environment Variables.")
    else:
        bot.run(TOKEN)
