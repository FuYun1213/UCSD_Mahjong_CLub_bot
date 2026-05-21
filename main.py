import discord
import gspread
import re
import os
import asyncio
import datetime
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from discord.ext import commands
from discord import app_commands
from typing import List
from discord.ext import tasks
from discord.ui import View, Button, Select, Modal, TextInput
from bot_action_log import record_action
# --- 1. 配置区域 ---
# ⚠️ 请确保您的 .env 文件名正确，如果是 .env 只需要 load_dotenv()
load_dotenv('DISCORD_BOT_TOKEN.env') 
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
SHEET_ID = "1Ce5k2Blbf5MYXbM4rSTeWHOf2uTHPrvZX6vm6Cdyc5Q" 
JSON_KEYFILE = 'credentials.json'
# ⚠️ 请替换为您服务器的真实ID
GUILD_ID = discord.Object(id=1278056421224747162) 
WWYD_GUILD_ID = discord.Object(id=1323725275950878840)
data_lock = asyncio.Lock()

# --- 2. 连接 Google Cloud ---
print("正在连接 Google Cloud...")
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
try:
    creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_KEYFILE, scope)
    gc = gspread.authorize(creds)
    # 测试连接
    spreadsheet = gc.open_by_key(SHEET_ID)

    print("✅ Google Sheet 连接成功")
except Exception as e:
    print(f"❌ 连接失败: {e}")
    # 如果连不上Google，程序继续运行也没意义，直接退出
    exit()

if BOT_TOKEN is None:
    print("❌ 错误：未找到 Token")
    exit()

# --- 3. 名字缓存与工具函数 ---
PLAYER_NAME_CACHE = []

def update_player_cache():
    global PLAYER_NAME_CACHE
    try:
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.worksheet("Ratings")
        all_names = ws.col_values(1)
        if len(all_names) > 1:
            PLAYER_NAME_CACHE = [name for name in all_names[1:] if name.strip()]
        else:
            PLAYER_NAME_CACHE = []
        print(f"✅ 已缓存 {len(PLAYER_NAME_CACHE)} 个玩家名字")
    except Exception as e:
        print(f"❌ 读取名字列表失败: {e}")


# --- 4. 机器人核心类定义 ---
intents = discord.Intents.default()
intents.message_content = True # 必须开启，否则无法读取消息内容
intents.members = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # 1. 🥇 第一步：加载所有外部模块 (Cogs)
        await self.load_extension("cogs.quarterupdate")
        await self.load_extension("cogs.personaldata")
        await self.load_extension("cogs.recordgame")
        await self.load_extension("cogs.revert")
        await self.load_extension("cogs.replaymonitor")
        await self.load_extension("cogs.versus")
        await self.load_extension("cogs.wwydtracker")
        print("✅ 模块加载完成 (Cogs loaded)！")

        # Copy the freshly loaded global cog commands into the main guild first.
        self.tree.copy_global_to(guild=GUILD_ID)
        await self.tree.sync(guild=GUILD_ID)
        await self.tree.sync(guild=WWYD_GUILD_ID)

        # Then delete stale global commands from Discord so duplicates do not appear.
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        print(f"✅ 指令已同步 (Synced to Guild)！")
        

client = MyBot()
def get_player_recent_stats(player_name, search_limit=500):
    try:
        sh = gc.open_by_key(SHEET_ID)
        
        # 1. 同时读取两个表格的所有数据
        ws_riichi = sh.worksheet("Games Riichi")
        ws_dates = sh.worksheet("Games/pt") 
        
        raw_riichi = ws_riichi.get_all_values()
        raw_dates = ws_dates.get_all_values()
        
        if not raw_riichi or len(raw_riichi) < 2:
            return None, "表格看起来是空的。"

        # 2. 合并数据
        combined_data = []
        max_rows = min(len(raw_riichi), len(raw_dates))
        
        for i in range(1, max_rows):
            r_row = raw_riichi[i] 
            d_row = raw_dates[i] 
            
            if r_row and len(r_row) > 0 and r_row[0].strip() != "":
                date_str = d_row[0] if len(d_row) > 0 else "Unknown Date"
                combined_data.append({
                    "data": r_row, 
                    "date": date_str 
                })

        # 3. 截取最后 search_limit 条
        search_data = combined_data[-search_limit:]
        
        matches = []
        current_mmr = "N/A"
        last_delta = "N/A"
        total_delta_sum = 0.0
        target_name = player_name.lower().strip()
        
        seen_games = set()

        # 4. 倒序查找
        for item in reversed(search_data):
            row = item["data"]
            date = item["date"]
            
            if len(row) < 4: continue
            
            # --- 去重逻辑 ---
            game_fingerprint = f"{date}|{'|'.join(row[0:4])}"
            if game_fingerprint in seen_games:
                continue
            seen_games.add(game_fingerprint)
            
            # --- 匹配名字 ---
            row_names = [str(n).lower().strip() for n in row[0:4]]
            
            found = False
            idx = -1 # 目标玩家在当前局的座位索引 (0-3)
            for i, name in enumerate(row_names):
                if target_name in name:
                    found = True
                    idx = i
                    break
            
            if found:
                # 提取目标玩家分数和变动
                score = row[4 + idx] if len(row) > 4+idx else "0"
                this_game_delta = row[8 + idx] if len(row) > 8+idx else "0"
                # 计算排名 (原有逻辑)
                try:
                    all_scores = []
                    for i in range(4):
                        s_val = float(row[4+i]) if len(row) > 4+i and row[4+i] else -99999
                        all_scores.append(s_val)
                        d_val = float(str(this_game_delta).strip())
                    total_delta_sum += d_val
                    my_score = all_scores[idx]
                    rank = sum(1 for s in all_scores if s > my_score) + 1
                except:
                    rank = "?"

                # 记录 MMR (原有逻辑)
                if current_mmr == "N/A":
                    last_delta = this_game_delta
                    current_mmr = row[12 + idx] if len(row) > 12+idx else "?"
                
                # ==========================================
                # ✨ 新增功能：生成全员战绩字符串 ✨
                # ==========================================
                details_list = []
                for i in range(4):
                    # 获取当前遍历到的玩家名字和分数
                    p_name = row[i] if len(row) > i else "Unknown"
                    p_score = row[4+i] if len(row) > 4+i else "0"
                    
                    # 格式化字符串
                    if i == idx:
                        # 如果是目标玩家，加粗显示
                        details_list.append(f"**{p_name} {p_score}**")
                    else:
                        # 其他玩家正常显示
                        details_list.append(f"{p_name} {p_score}")
                
                # 用逗号或者竖线连接，例如: "UserA 25000, **UserB 35000**, UserC 10000..."
                full_details_str = " | ".join(details_list) 
                # ==========================================

                matches.append({
                    "date": date,
                    "rank": rank,
                    "score": score,
                    "delta": this_game_delta,
                    "details": full_details_str # <--- ✅ 这里增加了详情字段
                })
                
                if len(matches) >= 5: break
        
        sign = "+" if total_delta_sum >= 0 else ""
        formatted_sum = f"{sign}{total_delta_sum:.1f}"

        return matches, {"mmr": current_mmr, "sum_delta": formatted_sum}

    except Exception as e:
        print(f"查表报错: {e}")
        return None, str(e)
async def player_name_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    if not PLAYER_NAME_CACHE:
        update_player_cache()
    
    choices = [
        app_commands.Choice(name=name, value=name)
        for name in PLAYER_NAME_CACHE
        if current.lower() in name.lower()
    ]
    return choices[:25]
# --- 1.3 获取排行榜数据的函数 ---
def get_ranking_data(category):
    try:
        sh = gc.open_by_key(SHEET_ID)
        
        # 1. 根据类别选择工作表 (Sheet)
        if "quarter" in category:
            sheet_name = "Ranking Quarter"
        else:
            sheet_name = "Ranking"
            
        ws = sh.worksheet(sheet_name)
        rows = ws.get_all_values()
        
        # 2. 根据类别选择列索引 (Column Index)
        # 索引从0开始: A=0, B=1, ... D=3, E=4 ... G=6, H=7
        if "mmr" in category:
            name_idx, score_idx = 0, 1 # A, B列
            label = "MMR"
        elif "pt" in category:
            name_idx, score_idx = 3, 4 # D, E列
            label = "PT"
        elif "games" in category:
            name_idx, score_idx = 6, 7 # G, H列
            label = "Games"
        else:
            return None, "未知榜单类型"

        data_list = []
        
        # 3. 遍历并提取数据 (从第2行开始，跳过标题)
        for row in rows[1:]:
            # 确保这一行够长，防止越界
            if len(row) <= score_idx: continue
            
            name = row[name_idx].strip()
            score_str = row[score_idx].strip()
            
            # 如果名字或分数是空的，跳过
            if not name or not score_str: continue
            
            try:
                # 尝试转成数字排序
                score = float(score_str)
                data_list.append({"name": name, "score": score})
            except:
                continue # 如果分数不是数字（比如表头混进来了），跳过

        # 4. 排序 (从大到小)
        # key=lambda x: x["score"] 表示按分数排
        sorted_data = sorted(data_list, key=lambda x: x["score"], reverse=True)
        
        # 只取前 15 名，防止刷屏
        return {
            "title": f"{label} Ranking ({sheet_name})",
            "data": sorted_data[:15], 
            "label": label
        }, None

    except Exception as e:
        print(f"Ranking Error: {e}")
        return None, str(e)
def update_config(key, value):
    """更新 Config 表 (通用函数保持不变)"""
    sh = gc.open_by_key(SHEET_ID)
    try: ws = sh.worksheet("Config")
    except: ws = sh.add_worksheet("Config", rows=100, cols=2)
    
    cell = ws.find(key)
    if cell: ws.update_cell(cell.row, 2, value)
    else: ws.append_row([key, value])

def get_quarter_config():
    """读取 Quarter 起止时间"""
    try:
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.worksheet("Config")
        data = ws.get_all_values()
        
        # 🟢 改为查找 quarter_start 和 quarter_end
        config = {"start": None, "end": None}
        config_dict = {row[0]: row[1] for row in data if len(row) >= 2}
        
        s_str = config_dict.get("quarter_start")
        e_str = config_dict.get("quarter_end")
        
        if s_str:
            config["start"] = datetime.datetime.strptime(s_str, "%Y-%m-%d")
        if e_str:
            config["end"] = datetime.datetime.strptime(e_str, "%Y-%m-%d") + datetime.timedelta(days=1)
            
        return config
    except Exception as e:
        print(f"Config Error: {e}")
        return None
def get_accumulated_stats(start_date, end_date=None):
    """
    统计 start_date 到 end_date 之间的所有数据
    包含：自动清洗中文符号、适配多种日期格式
    """
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet("Games/pt")
    rows = ws.get_all_values()
    
    if not end_date:
        end_date = datetime.datetime.now()

    stats = {} 
    
    for row in rows[1:]:
        if not row[0]: continue
        
        # 1. 获取原始字符串
        raw_date_str = row[0].strip()
        
        # 🧹 2. 数据清洗 (关键步骤！)
        # 把中文冒号 '：' 替换成英文冒号 ':'
        # 把多个空格缩减为一个，防止 '1/5/2026  14:30' 这种情况
        clean_date_str = raw_date_str.replace("：", ":").replace("  ", " ")
        
        game_date = None
        
        # 3. 定义可能遇到的格式
        date_formats = [
            "%m/%d/%Y %H:%M",     # 您的目标格式: 01/05/2026 14:30
            "%m/%d/%Y %H:%M:%S",  # 带秒: 01/05/2026 14:30:00
            "%Y-%m-%d %H:%M",     # 备用: 2026-01-05 14:30
            "%Y-%m-%d %H:%M:%S",  # 备用: 2026-01-05 14:30:00
            "%Y/%m/%d %H:%M",     # 备用: 2026/01/05 14:30 (年月倒过来)
        ]
        
        for fmt in date_formats:
            try:
                game_date = datetime.datetime.strptime(clean_date_str, fmt)
                break 
            except ValueError:
                continue 
        
        # 如果还是读不出来，打印错误方便调试
        if game_date is None:
            # print(f"⚠️ 跳过无法解析的日期: {raw_date_str}")
            continue
        
        # 4. 统计逻辑 (保持不变)
        if start_date <= game_date < end_date:
            for i in range(4):
                name_idx = 1 + i*3
                pt_idx = 3 + i*3
                if len(row) <= pt_idx: continue
                name = row[name_idx].strip().lower()
                if not name: continue
                try: pt = float(row[pt_idx])
                except: pt = 0
                
                if name not in stats: stats[name] = {'games': 0, 'pt': 0.0}
                stats[name]['games'] += 1
                stats[name]['pt'] += pt
                
    return stats
# --- 7. Slash Command 指令 ---
@client.tree.command(name="recent_match", description="查询最近 5 场对局记录及同桌分数")
@app_commands.describe(player_name="输入玩家名字")
@app_commands.autocomplete(player_name=player_name_autocomplete)
async def recent_match(interaction: discord.Interaction, player_name: str):
    # 1. 告诉 Discord 我们在处理 (防止超时)
    await interaction.response.defer()

    # 2. 调用我们在上一轮修改好的函数
    # 注意：确保 get_player_recent_stats 已经是最新版 (包含了 details 字段逻辑)
    matches, stats = get_player_recent_stats(player_name)

    # 3. 错误处理
    if not matches:
        # 如果 stats 是字符串，说明是报错信息
        error_msg = stats if isinstance(stats, str) else "找不到该玩家的数据。"
        await interaction.followup.send(f"❌ 查询失败: {error_msg}")
        return

    # 4. 创建 Embed 面板
    current_mmr = stats.get('mmr', 'N/A')
    last_delta = stats.get('delta', 'N/A')
    
    embed = discord.Embed(
        title=f"📊 {player_name} 的最近战绩",
        description=f"**Current MMR:** `{current_mmr}` (Sum: {last_delta})",
        color=0x3498db # 蓝色
    )

    # 5. 遍历每一局数据并添加到面板
    # 映射排名到 Emoji
    rank_emojis = {1: "🐶", 2: "🥈", 3: "🥉", 4: "🪦"}

    for game in matches:
        date = game['date']
        rank = game['rank']
        score = game['score']
        delta = game['delta']
        
        # 👉 关键点：取出我们在上一轮增加的 'details' 字段
        # 如果你没更新 get_player_recent_stats，这里会取到默认值
        details_str = game.get('details', "暂无详情数据")

        # 处理一下排名 Emoji
        # 如果 rank 是 "?" (有时候计算出错), 默认给个圆圈
        r_num = int(rank) if str(rank).isdigit() else 4
        emoji = rank_emojis.get(r_num, "🎲")
        field_title = f"{emoji} {date} | Rank #{rank} ({delta})"
        
        # 组合内容：显示同桌详情
        # 这里直接把拼接好的 details_str 放进去
        field_value = f"Your Score: **{score}**\nTable: {details_str}"

        embed.add_field(
            name=field_title,
            value=field_value,
            inline=False # 设为 False 让每一局独占一行，排版更整齐
        )

    # 6. 发送结果
    await interaction.followup.send(embed=embed)
    # ✅ 正确：defer 之后必须用 followup
    #await interaction.followup.send(f"🔍 Searching data for **{player_name}** ...")
    
    match_history, stats = get_player_recent_stats(player_name)
    
    if match_history is None:
        await interaction.edit_original_response(content=f"Error: {stats}")
        return
        
    if not match_history:
        await interaction.edit_original_response(content=f"No recent records found for **{player_name}**.")
        return
    
    mmr_val = stats['mmr']
    total_delta = 0
    for m in match_history:
        try:
            # 尝试把变动值转成数字相加
            total_delta += float(m['delta'])
        except:
            pass # 如果是 "?" 或其他非数字，忽略
            
    # 格式化显示的字符串 (正数加号，保留1位小数)
    if total_delta > 0:
        sum_str = f"+{total_delta}"
    else:
        sum_str = f"{total_delta}"
    
    # 如果是整数，去掉 .0 (可选，看你喜好)
    if sum_str.endswith(".0"):
        sum_str = sum_str[:-2]

    msg = f"**Mathch History for {player_name}** \n"
    msg += f"**Current MMR**: `{mmr_val}` (Recent 5 Change: `{sum_str}`)\n"
    msg += "-----------------------------------\n"
    msg += "**Recent 5 Games:**\n"
    
    for m in match_history:
        #rank_icon = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣"}.get(m['rank'], "❓")
        
        # 处理变动符号
        delta_str = m['delta']
        try:
            if float(delta_str) > 0: delta_str = f"+{delta_str}"
        except: pass
        
        # ✅ 修改这里：把日期加在前面
        # 格式示例: 🥇 [01/08/2026 12:00] #1 | Score: 35000 (+15)
        msg += f"**[{m['date']}]** #{m['rank']} | Score: `{m['score']}` ({delta_str})\n"
    
    msg += "-----------------------------------"
    
    await interaction.edit_original_response(content=msg)
from discord import app_commands # 确保引用了这个

@client.tree.command(name="ranking", description="查看服务器排行榜 (MMR / PT / 场次)")
@app_commands.describe(category="请选择要查看的榜单类型")
@app_commands.choices(category=[
    app_commands.Choice(name="Total MMR (总榜)", value="total_mmr"),
    app_commands.Choice(name="Total PT (总榜)", value="total_pt"),
    app_commands.Choice(name="Total Games (总肝帝)", value="total_games"),
    app_commands.Choice(name="Quarter MMR (本季)", value="quarter_mmr"),
    app_commands.Choice(name="Quarter PT (本季)", value="quarter_pt"),
    app_commands.Choice(name="Quarter Games (本季肝帝)", value="quarter_games")
])
async def ranking(interaction: discord.Interaction, category: app_commands.Choice[str]):
    await interaction.response.defer()
    
    # category.value 就是上面 value=... 里的字符串
    lb_data, error = get_ranking_data(category.value)
    
    if lb_data is None:
        await interaction.followup.send(f"❌ 获取榜单失败: {error}")
        return
        
    data = lb_data["data"]
    title = lb_data["title"]
    label = lb_data["label"]
    
    # --- 构建显示的文本 ---
    desc_lines = []
    
    for i, item in enumerate(data):
        rank = i + 1
        name = item["name"]
        score = item["score"]
        
        # 奖牌特效
        if rank == 1: icon = "🥇"
        elif rank == 2: icon = "🥈"
        elif rank == 3: icon = "🥉"
        else: icon = f"`#{rank}`" # 4名以后显示 #4, #5
        
        # 格式化: 🥇 **Name**: 1500 MMR
        # 对于分数，如果是整数就去小数点 (比如场次)，如果是小数保留1位
        if label == "Games":
            score_str = f"{int(score)}"
        else:
            score_str = f"{score:.1f}"
            
        line = f"{icon} **{name}** \u200b \u200b `{score_str}`"
        desc_lines.append(line)
        
    if not desc_lines:
        desc_lines.append("暂时没有数据...")

    # --- 发送 Embed ---
    embed = discord.Embed(
        title=f"📊 {title}",
        description="\n".join(desc_lines),
        color=0xFFD700 # 金色
    )
    # 加个脚标显得专业
    embed.set_footer(text="Data updated from Google Sheets")
    
    await interaction.followup.send(embed=embed)
@client.tree.command(name="set_quarter", description="[管理员] 设定本 Quarter 的起止日期")
@app_commands.describe(start_date="开始日期 (2026-01-01)", end_date="结束日期 (2026-03-30)")
# 🛡️ 核心修改：只有服务器管理员能用
@app_commands.default_permissions(administrator=True) 
async def set_quarter(interaction: discord.Interaction, start_date: str, end_date: str):
    await interaction.response.defer(ephemeral=True) # 只有管理员自己能看到回复
    
    # 1. 日期格式检查
    try:
        datetime.datetime.strptime(start_date, "%Y-%m-%d")
        datetime.datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        await interaction.followup.send("❌ 日期格式错误！请使用 `YYYY-MM-DD` 格式 (例如 2026-01-01)。")
        return

    # 2. 写入 Config 表
    try:
        # 更新配置
        update_config("quarter_start", start_date)
        update_config("quarter_end", end_date)
        
        await interaction.followup.send(f"✅ **Winter Quarter** 时间已更新！\n📅 `{start_date}` ⮕ `{end_date}`")
    except Exception as e:
        await interaction.followup.send(f"❌ 设置失败: {e}")
# main.py 中新增的注册功能

@client.tree.command(name="register", description="注册新玩家 (Register a new player)")
@app_commands.describe(new_name="Please enter your ID")
async def register(interaction: discord.Interaction, new_name: str):
    global PLAYER_NAME_CACHE 
    await interaction.response.defer(ephemeral=False)
    
    new_name = new_name.strip()


    if any(name.lower() == new_name.lower() for name in PLAYER_NAME_CACHE):
        await interaction.followup.send(f"❌ Registration Failed.name **{new_name}** is already taken")
        return

    try:
        result = await asyncio.to_thread(perform_google_sheet_registration, new_name)
        result_msg = result["message"] if isinstance(result, dict) else result
        if "成功" in result_msg:
            # 只有当本地列表里还没有这个名字时才添加 (双重保险)
            if new_name not in PLAYER_NAME_CACHE:
                PLAYER_NAME_CACHE.append(new_name)
                print(f"✅ 本地缓存已手动追加: {new_name}")
            if isinstance(result, dict):
                record_action(
                    user_id=interaction.user.id,
                    user_name=str(interaction.user),
                    action_type="register",
                    summary=f"Registered player {new_name}",
                    payload={
                        "ratings_row": result["row_number"],
                        "ratings_values": result["row_values"],
                    },
                )

            await interaction.followup.send(f"✅ {result_msg}")
        else:
            await interaction.followup.send(f"❌ {result_msg}")
    except Exception as e:
        await interaction.followup.send(f"❌ 系统错误: {e}")

# --- 辅助函数：负责具体的 Google Sheets 写入操作 ---
# 这个函数是同步的，被上面用 to_thread 调用，防止阻塞 Bot
def perform_google_sheet_registration(player_name):
    try:
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.worksheet("Ratings")
        
        # 获取第一列的所有值，用来计算哪里是空行
        # col_values(1) 返回的是一个列表，len(col_values) + 1 就是下一个空行的行号
        # 注意：如果中间有空行，这种方法可能会插在中间。
        # 最稳健的方法是 append_row
        
        # 准备要写入的一行数据： [名字, 初始分]
        # 假设名字在 A 列 (第1列)，分数在 B 列 (第2列)
        new_row = [player_name, 1500]
        new_row_number = len(ws.col_values(1)) + 1
        
        # append_row 会自动寻找表格最底部的空行写入，非常方便且安全
        ws.append_row(new_row)
        
        return {
            "message": f"注册成功！欢迎 **{player_name}** 加入。初始分数: 1500",
            "row_number": new_row_number,
            "row_values": new_row,
        }
    except Exception as e:
        print(f"写入 Google Sheet 失败: {e}")
        return f"数据库写入失败: {e}"

# --- 9. 启动 ---
@client.event
async def on_ready():
    print(f'🤖 登录成功：{client.user}')
    print("正在加载玩家名单缓存...")
    update_player_cache()

# 最后一行才是 run
client.run(BOT_TOKEN)
