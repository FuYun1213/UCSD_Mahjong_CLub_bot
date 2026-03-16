import discord
import gspread
import re
import os
import json
import urllib.parse
import asyncio
import datetime
import pandas as pd
from datetime import datetime,timedelta,timezone
from collections import Counter
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from datetime import timedelta 
from discord.ext import commands
from discord import app_commands
from typing import List
from discord.ext import tasks
from mahjong_ui import SeatSelectView
from discord.ui import View, Button, Select, Modal, TextInput
# --- 1. 配置区域 ---
# ⚠️ 请确保您的 .env 文件名正确，如果是 .env 只需要 load_dotenv()
load_dotenv('DISCORD_BOT_TOKEN.env') 
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
SHEET_ID = "1Ce5k2Blbf5MYXbM4rSTeWHOf2uTHPrvZX6vm6Cdyc5Q" 
JSON_KEYFILE = 'credentials.json'
# ⚠️ 请替换为您服务器的真实ID
GUILD_ID = discord.Object(id=1278056421224747162) 
DATA_FILE = 'mahjong_records.csv'
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

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # 1. 🥇 第一步：加载所有外部模块 (Cogs)
        await self.load_extension("cogs.quarterupdate")
        print("✅ 模块加载完成 (Cogs loaded)！")

        self.tree.copy_global_to(guild=GUILD_ID)

        await self.tree.sync(guild=GUILD_ID)
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
# --- 1.1 新增：获取详细个人数据的函数 ---
def get_personal_detailed_data(player_name):
    try:
        sh = gc.open_by_key(SHEET_ID)
        target_name = player_name.lower().strip()
        
        # --- A. 读取 Personal Data 表 (基础数据) ---
        ws_personal = sh.worksheet("Personal Data")
        # 假设第一行是表头，从第二行开始
        data_personal = ws_personal.get_all_values()
        
        personal_info = None
        # 遍历查找玩家
        for row in data_personal[1:]:
            if row and row[0].strip().lower() == target_name:
                # 找到玩家，提取数据
                # A(0):Name ... C(2):AvgPlace ... F(5):AvgPoint ... 
                # K(10):1st ... N(13):4th ... O(14):TotalGames
                personal_info = {
                    "avg_place": row[2],
                    "avg_point": row[5],
                    "count_1st": row[10],
                    "count_2nd": row[11],
                    "count_3rd": row[12],
                    "count_4th": row[13],
                    "total_games": row[14]
                }
                break
        
        if not personal_info:
            return None, "In 'Personal Data' sheet, player not found."
        quarter_pt="N/A"
        try:
            ws_winter = sh.worksheet("Personal Data Quarter")
            data_winter = ws_winter.get_all_values()
            for row in data_winter[2:]:
                if row and row[0].strip().lower() == target_name:
                    quarter_pt = row[2] 
                    break
        except Exception as e:
            print(f"Quarter PT sheet error: {e}")
            quarter_pt = "N/A"

        ws_pt = sh.worksheet("Games/pt")
        raw_pt = ws_pt.get_all_values()
        pt_changes = []
        for row in reversed(raw_pt[1:]):
            if len(row) < 13: continue 
            
            found_pt = False
            delta_pt = 0
            
            # 位置映射: 名字索引(B,E,H,K) -> PT索引(D,G,J,M)
            check_indices = {1: 3, 4: 6, 7: 9, 10: 12}
            
            for name_idx, score_idx in check_indices.items():
                if len(row) > name_idx and target_name in row[name_idx].lower().strip():
                    try:
                        val = row[score_idx]
                        delta_pt = float(val) if val else 0
                        found_pt = True
                    except:
                        delta_pt = 0
                    break
            
            if found_pt:
                pt_changes.append(delta_pt)
                if len(pt_changes) >= 10: break
        # --- C. 读取 Games Riichi 表 (统计 MMR 变化、绝对值 和 顺位历史) ---
        ws_riichi = sh.worksheet("Games Riichi")
        raw_riichi = ws_riichi.get_all_values()
        
        mmr_changes = []        # 存变动值 (比如 +15)
        recent_ranks = []       # 存顺位 (比如 1, 2)
        mmr_absolute_history = [] # 存绝对值 (比如 1500) 用于画图
        current_mmr = "N/A"
        
        # 倒序查找
        for row in reversed(raw_riichi[1:]):
            if len(row) < 4: continue
            
            row_names = [str(n).lower().strip() for n in row[0:4]]
            
            # === 🔴 缺失的就是这一段查找逻辑 ===
            found_mmr = False
            idx = -1
            
            # 遍历这一行的4个玩家名字，看有没有目标玩家
            for i, name in enumerate(row_names):
                if target_name in name:
                    idx = i
                    found_mmr = True
                    break
            
            if found_mmr:
                if current_mmr == "N/A":
                    try:
                        # 绝对值在 M-P 列 (索引 12-15)
                        abs_val_str = row[12 + idx] if len(row) > 12+idx else "0"
                        current_mmr = abs_val_str # 存下来
                    except:
                        current_mmr = "Error"
                # 1. 获取 MMR 变动 (I-L列, 索引 8-11)
                try:
                    delta = row[8 + idx] if len(row) > 8+idx else "0"
                    mmr_val = float(delta)
                except:
                    mmr_val = 0
                mmr_changes.append(mmr_val)
                
                # 2. 获取 MMR 绝对值 (M-P列, 索引 12-15) -> 🟢 画图用这个
                try:
                    abs_val_str = row[12 + idx] if len(row) > 12+idx else "0"
                    # 如果为空或者是 "-"，用0代替
                    abs_val = float(abs_val_str) if abs_val_str.strip() else 0
                except:
                    abs_val = 0
                mmr_absolute_history.append(abs_val)
                
                # 3. 计算顺位
                try:
                    all_scores = []
                    for i in range(4):
                        s = float(row[4+i]) if len(row) > 4+i and row[4+i] else -99999
                        all_scores.append(s)
                    my_s = all_scores[idx]
                    rank = sum(1 for s in all_scores if s > my_s) + 1
                    recent_ranks.append(str(rank))
                except:
                    recent_ranks.append("?")
                
                if len(mmr_changes) >= 10: break

        # 🟢 别忘了翻转绝对值列表，因为我们是倒序读的
        mmr_absolute_history.reverse()
        
        # 返回所有数据
        return {
            "info": personal_info,
            "pt_history": pt_changes,
            "mmr_history": mmr_changes,
            "rank_history": recent_ranks,
            "mmr_chart_data": mmr_absolute_history, 
            "current_mmr": current_mmr,  # 🟢 返回当前 MMR
            "quarter_pt": quarter_pt   # 🟢 返回本学期 PT
        }, None

    except Exception as e:
        print(f"Personal Data Error: {e}")
        return None, str(e)
# --- 新增：生成 QuickChart URL 的函数 ---
def get_mmr_chart_url(mmr_values):
    """
    接收一个 MMR 数值列表，返回一个折线图的图片 URL
    """
    if not mmr_values or len(mmr_values) < 2:
        # 数据太少画不了图，返回 None
        return None

    # QuickChart 的配置 JSON
    chart_config = {
        "type": "line",
        "data": {
            # x轴标签：第1局, 第2局...
            "labels": [str(i+1) for i in range(len(mmr_values))],
            "datasets": [{
                "label": "MMR Trend",
                "data": mmr_values, # y轴数据
                "borderColor": "rgb(75, 192, 192)", # 线条颜色(青色)
                "backgroundColor": "rgba(75, 192, 192, 0.2)", # 填充颜色
                "fill": True, # 是否填充线条下方区域
                "tension": 0.3, # 线条平滑度(0是折线，0.4是曲线)
                "pointRadius": 3, # 数据点大小
            }]
        },
        "options": {
            "legend": {"display": False}, # 隐藏图例
            "title": {
                "display": True, 
                "text": f"Recent {len(mmr_values)} Games MMR Trend",
                "fontColor": "#333"
            },
            "scales": {
                # 让Y轴不必从0开始，而是根据数据范围自动调整，图表更有波动感
                "yAxes": [{"ticks": {"beginAtZero": False}}] 
            }
        }
    }
    
    # 1. 把字典转成 JSON 字符串
    chart_json = json.dumps(chart_config)
    # 2. 把 JSON 字符串进行 URL 编码
    encoded_json = urllib.parse.quote(chart_json)
    # 3. 拼接完整 URL (使用 https)
    url = f"https://quickchart.io/chart?c={encoded_json}&w=500&h=300"
    
    return url
# --- 6. 自动补全函数 ---
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
# --- 1.2 获取两人对决数据的函数 (显示真实名字版) ---
# --- 1.2 获取两人对决数据的函数 (含大胜/踩头统计) ---
def get_versus_data(player_a, player_b):
    try:
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.worksheet("Games Riichi")
        rows = ws.get_all_values()
        
        p1 = player_a.lower().strip()
        p2 = player_b.lower().strip()
        
        if p1 == p2:
            return None, "请输入两个不同的名字。"

        stats = {
            "total_matches": 0,
            "p1_stats": {"wins": 0, "big_wins": 0, "stomps": 0, "weighted_score": 0},
            "p2_stats": {"wins": 0, "big_wins": 0, "stomps": 0, "weighted_score": 0},
            "p1_pt_diff": 0.0, # 使用 PT 做分差
            "recent_record": [] 
        }

        last_game_signature = ""

        for row in rows[1:]:
            if len(row) < 8: continue 
            
            # --- 去重 ---
            current_signature = "".join([str(x).strip().lower() for x in row[0:8]])
            if current_signature == last_game_signature:
                continue
            last_game_signature = current_signature
            
            # 获取玩家列表
            current_players = [n.lower().strip() for n in row[0:4]]
            
            if p1 in current_players and p2 in current_players:
                stats["total_matches"] += 1
                
                # 1. 获取本局 4 个人的分数，算出排名
                # 注意：这里用 Raw Score (4-7列) 来算绝对排名最稳妥
                scores_for_rank = []
                for i in range(4):
                    try:
                        s = float(row[4+i])
                    except: s = -999999
                    scores_for_rank.append(s)
                
                # 找到 A 和 B 在本局的得分
                idx_1 = current_players.index(p1)
                idx_2 = current_players.index(p2)
                score_val_1 = scores_for_rank[idx_1]
                score_val_2 = scores_for_rank[idx_2]
                
                # 2. 计算排名 (1-4)
                # 逻辑：比我分高的人数 + 1 = 我的排名
                rank_1 = sum(1 for s in scores_for_rank if s > score_val_1) + 1
                rank_2 = sum(1 for s in scores_for_rank if s > score_val_2) + 1
                
                # 3. 计算 PT 差 (用于直击点差) - 抓取 8-11 列
                try: pt_1 = float(row[4 + idx_1])
                except: pt_1 = 0
                try: pt_2 = float(row[4 + idx_2])
                except: pt_2 = 0
                stats["p1_pt_diff"] += (pt_1 - pt_2)

                # 4. 判定胜负类型
                winner = "Draw"
                rank_diff = abs(rank_1 - rank_2)
                
                if rank_1 < rank_2: # P1 赢 (排名数字小=名次高)
                    winner = player_a
                    stats["p1_stats"]["wins"] += 1
                    
                    if rank_diff == 3: # 1位 vs 4位 -> 踩头
                        stats["p1_stats"]["stomps"] += 1
                        stats["p1_stats"]["weighted_score"] += 3 # 1+2
                    elif rank_diff == 2: # 1位 vs 3位 / 2位 vs 4位 -> 大胜
                        stats["p1_stats"]["big_wins"] += 1
                        stats["p1_stats"]["weighted_score"] += 2 # 1+1
                    else:
                        stats["p1_stats"]["weighted_score"] += 1 # 普通胜

                elif rank_2 < rank_1: # P2 赢
                    winner = player_b
                    stats["p2_stats"]["wins"] += 1
                    
                    if rank_diff == 3:
                        stats["p2_stats"]["stomps"] += 1
                        stats["p2_stats"]["weighted_score"] += 3
                    elif rank_diff == 2:
                        stats["p2_stats"]["big_wins"] += 1
                        stats["p2_stats"]["weighted_score"] += 2
                    else:
                        stats["p2_stats"]["weighted_score"] += 1

                stats["recent_record"].append(winner)
                if len(stats["recent_record"]) > 5:
                    stats["recent_record"].pop(0)

        if stats["total_matches"] == 0:
            return None, f"未找到 {player_a} 和 {player_b} 同桌记录。"
            
        return stats, None

    except Exception as e:
        print(f"Versus Error: {e}")
        return None, str(e)
def get_local_player_stats(player_name):
    """从本地 CSV 读取并计算个人详细战绩"""
    csv_file = 'mahjong_records.csv'
    
    # 1. 检查文件是否存在
    if not os.path.exists(csv_file):
        return None

    try:
        df = pd.read_csv(csv_file)
        
        # 2. 筛选该玩家的数据
        # 确保 player 列存在且匹配
        player_df = df[df['player'] == player_name]
        
        total_rounds = len(player_df)
        if total_rounds == 0:
            return None # 有文件但没这个人的记录

        # 3. 计算 和率 & 铳率
        # 和牌次数
        win_count = len(player_df[player_df['action'] == '和牌'])
        # 点炮次数
        deal_in_count = len(player_df[player_df['action'] == '点炮'])
        
        win_rate = (win_count / total_rounds) * 100
        deal_in_rate = (deal_in_count / total_rounds) * 100

        # 4. 统计最喜欢的役种 (排除 Dora)
        all_yaku = []
        # 只看和牌的记录
        win_rows = player_df[player_df['action'] == '和牌']
        
        for details in win_rows['details']:
            if pd.isna(details) or details == "N/A": continue
            
            # 分割字符串 "立直, 平和, 宝牌x2" -> ["立直", "平和", "宝牌x2"]
            yaku_list = [y.strip() for y in str(details).split(',')]
            
            for yaku in yaku_list:
                # 过滤掉包含 "宝牌" 或 "Dora" 的项
                if "宝牌" not in yaku and "Dora" not in yaku:
                    all_yaku.append(yaku)
        
        # 找出出现频率最高的 1 个役种
        if all_yaku:
            fav_yaku_data = Counter(all_yaku).most_common(1)
            fav_yaku_str = f"{fav_yaku_data[0][0]} ({fav_yaku_data[0][1]}次)"
        else:
            fav_yaku_str = "暂无数据"

        # 5. 寻找最近的大牌 (按点数排序)
        # 转换 points 列为数字 (防止 CSV 读取为字符串)
        win_rows = win_rows.copy() # 避免 SettingWithCopyWarning
        win_rows['points'] = pd.to_numeric(win_rows['points'], errors='coerce').fillna(0)
        
        if not win_rows.empty:
            # 找到点数最大的一行
            best_row = win_rows.loc[win_rows['points'].idxmax()]
            best_hand_str = f"**{int(best_row['points'])}点**\n{best_row['details']}\n({best_row['round']})"
        else:
            best_hand_str = "暂无和牌"

        return {
            "win_rate": f"{win_rate:.1f}%",
            "deal_in_rate": f"{deal_in_rate:.1f}%",
            "total_local_rounds": total_rounds,
            "fav_yaku": fav_yaku_str,
            "best_hand": best_hand_str
        }

    except Exception as e:
        print(f"❌ 读取本地数据失败: {e}")
        return None
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
# --- 1.4 获取指定玩家的实时排名和分数 (用于战报对比) ---
def get_players_status(player_names):
    """
    输入: ['Frank', 'John', ...]
    输出: 字典 {'Frank': {'mmr': 1500, 'mmr_rank': 1, 'pt': 200, 'pt_rank': 3}, ...}
    说明: 同时读取 'Ranking' (总分) 和 'Ranking Quarter' (季分)
    """
    # 1. 初始化: 给所有玩家填默认值，防止报错
    status = {name: {"mmr": 0, "mmr_rank": "Unranked", "pt": 0, "pt_rank": "Unranked"} for name in player_names}
    
    try:
        sh = gc.open_by_key(SHEET_ID)
        
        # ==========================================
        # 🟢 A 部分: 读取总榜 MMR (Ranking)
        # ==========================================
        try:
            ws_rank = sh.worksheet("Ranking")
            rows_rank = ws_rank.get_all_values()
            
            mmr_list = []
            # 假设 Ranking 表: A列=名字(0), B列=MMR(1)
            for row in rows_rank[1:]:
                if len(row) < 2 or not row[0]: continue
                try: 
                    mmr_list.append({"name": row[0].strip().lower(), "val": float(row[1])})
                except: continue
            
            # 排序 & 匹配
            mmr_list.sort(key=lambda x: x["val"], reverse=True)
            for rank, item in enumerate(mmr_list, 1):
                for target in player_names:
                    if item["name"] == target.lower():
                        status[target]["mmr"] = item["val"]
                        status[target]["mmr_rank"] = rank
        except Exception as e:
            print(f"⚠️ 读取 Ranking 失败: {e}")

        # ==========================================
        # 🔵 B 部分: 读取季度榜 PT (Ranking Quarter)
        # ==========================================
        try:
            ws_quarter = sh.worksheet("Ranking Quarter")
            rows_quarter = ws_quarter.get_all_values()
            
            pt_list = []
            # ⚠️ 注意：您代码里写的是 index 3 (D列) 和 index 4 (E列)
            # 如果您的表格其实是 A列(0) 和 B列(1)，请修改下面的数字！
            NAME_COL = 3  # D列
            PT_COL = 4    # E列
            
            for row in rows_quarter[1:]:
                # 检查列数够不够，防止越界
                if len(row) <= PT_COL or not row[NAME_COL]: continue
                try: 
                    p_name = row[NAME_COL].strip().lower()
                    p_pt = float(row[PT_COL])
                    pt_list.append({"name": p_name, "val": p_pt})
                except: continue
            
            # 排序 & 匹配
            pt_list.sort(key=lambda x: x["val"], reverse=True)
            for rank, item in enumerate(pt_list, 1):
                for target in player_names:
                    if item["name"] == target.lower():
                        status[target]["pt"] = item["val"]
                        status[target]["pt_rank"] = rank
        except Exception as e:
            print(f"⚠️ 读取 Ranking Quarter 失败: {e}")

        return status

    except Exception as e:
        print(f"❌ Get Status Critical Error: {e}")
        return status

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
@client.tree.command(name="personal_data", description="查询详细个人数据 (Total, PT, MMR, Avg, Local Stats)")
@app_commands.describe(player_name="请输入玩家名字")
@app_commands.autocomplete(player_name=player_name_autocomplete)
async def personal_data(interaction: discord.Interaction, player_name: str):
    # 使用 defer 来等待
    await interaction.response.defer(ephemeral=False)
    
    # --- 1. 获取 Google Sheets / 数据库 里的总体数据 (你原本的逻辑) ---
    data, error = get_personal_detailed_data(player_name)
    
    if data is None:
        await interaction.followup.send(content=f"❌ Error: {error}")
        return

    # --- 2. 获取 本地 CSV 里的详细对局数据 (新增逻辑) ---
    local_stats = get_local_player_stats(player_name)

    # --- 3. 解包原有数据 ---
    info = data["info"]
    pt_list = data["pt_history"]
    mmr_list = data["mmr_history"]
    rank_list = data["rank_history"]
    chart_data = data.get("mmr_chart_data", []) 
    current_mmr = data.get("current_mmr", "N/A")
    quarter_pt = data.get("quarter_pt", "N/A")
    
    sum_pt = sum(pt_list)
    sum_mmr = sum(mmr_list)
    pt_sign = "+" if sum_pt > 0 else ""
    mmr_sign = "+" if sum_mmr > 0 else ""
    recent_game_str = "".join(rank_list)

    # --- 4. 构建 Embed ---
    embed = discord.Embed(
        title=f"📊 Personal Data: {player_name}", 
        color=0x3498db
    )

    # A. 总体概况 (保持不变)
    embed.add_field(
        name="🔥 Current Status",
        value=f"**MMR**: `{current_mmr}`\n**Quarter PT**: `{quarter_pt}`",
        inline=False
    )
    
    embed.add_field(
        name="🏆 Total Games (Overall)", 
        value=f"`{info['total_games']}` Games\n[1st: `{info['count_1st']}` / 2nd: `{info['count_2nd']}` / 3rd: `{info['count_3rd']}` / 4th: `{info['count_4th']}`]",
        inline=False
    )

    # B. 【新增】详细战术数据 (来源于 CSV)
    if local_stats:
        embed.add_field(
            name="⚔️ Play Style (Local Records)",
            value=f"**和率 (Win)**: `{local_stats['win_rate']}`\n**铳率 (Deal-in)**: `{local_stats['deal_in_rate']}`\n(Based on {local_stats['total_local_rounds']} rounds)",
            inline=True
        )
        embed.add_field(
            name="❤️ Favorite Yaku",
            value=f"`{local_stats['fav_yaku']}`",
            inline=True
        )
        # 为了排版好看，Best Hand 单独占一行
        embed.add_field(
            name="💥 Recent Best Hand",
            value=local_stats['best_hand'],
            inline=False
        )
    else:
        # 如果没有本地记录，提示一下
        embed.add_field(
            name="⚔️ Play Style",
            value="*No detailed round records found.*",
            inline=False
        )

    # C. 原有的平均数据和趋势
    embed.add_field(
        name="📏 Averages", 
        value=f"Avg Place: `{info['avg_place']}`\nAvg Point: `{info['avg_point']}`",
        inline=True
    )
    
    embed.add_field(
        name="📈 Recent Trends (Last 10)", 
        value=f"PT Change: `{pt_sign}{sum_pt:.1f}`\nMMR Change: `{mmr_sign}{sum_mmr:.1f}`",
        inline=True
    )
    
    embed.add_field(
        name="🔄 Recent Form (Left=Latest)", 
        value=f"`[{recent_game_str}]`",
        inline=False
    )

    # --- 5. 设置图表 ---
    chart_url = get_mmr_chart_url(chart_data)
    if chart_url:
        embed.set_image(url=chart_url)
    else:
        embed.set_footer(text="Not enough data to generate MMR chart.")

    await interaction.followup.send(embed=embed)
@client.tree.command(name="versus", description="Query the match history between the two players.")
@app_commands.describe(player_a="选手 A", player_b="选手 B")
@app_commands.autocomplete(player_a=player_name_autocomplete, player_b=player_name_autocomplete)
async def versus(interaction: discord.Interaction, player_a: str, player_b: str):
    await interaction.response.defer()
    
    data, error = get_versus_data(player_a, player_b)
    if data is None:
        await interaction.followup.send(f"❌ {error}")
        return
        
    s1 = data["p1_stats"]
    s2 = data["p2_stats"]
    total = data["total_matches"]
    
    # 算出平局
    draws = total - s1["wins"] - s2["wins"]
    
    # --- 计算统治力 (Weighted Rate) ---
    score1 = s1["weighted_score"]
    score2 = s2["weighted_score"]
    total_score = score1 + score2
    
    if total_score > 0:
        rate_a = (score1 / total_score) * 100
        rate_b = (score2 / total_score) * 100
    else:
        rate_a = 50
        rate_b = 50
        
    # 进度条 (基于积分，而非胜场)
    bar_len = 12
    num_a = int((rate_a / 100) * bar_len)
    num_b = int((rate_b / 100) * bar_len)
    # 修正浮点误差导致的长度不足
    if num_a + num_b < bar_len and total_score > 0:
        if rate_a >= rate_b: num_a += 1
        else: num_b += 1
        
    bar_str = "🟦" * num_a + "🟥" * num_b
    while len(bar_str) < bar_len: bar_str += "⬜"

    # 评语逻辑
    diff_rate = abs(rate_a - rate_b)
    leader = player_a if rate_a > rate_b else player_b
    loser = player_b if rate_a > rate_b else player_a
    
    comment = "势均力敌！"
    if total < 5: comment = "刚开始较量..."
    elif diff_rate > 40: comment = f"{leader} 正在对 {loser} 进行降维打击！💥"
    elif diff_rate > 20: comment = f"{leader} 掌握了绝对的统治力！"
    elif diff_rate > 10: comment = f"{leader} 稍占上风。"

    # --- 构建 Embed ---
    embed = discord.Embed(
        title=f"⚔️: {player_a} 🆚 {player_b}",
        description=f"Total **{total}** Games | {comment}",
        color=0xFF4500
    )
    
    # 1. 核心胜场数据
    embed.add_field(
        name="📊 总胜场",
        value=f"**{player_a}**: `{s1['wins']}` 胜\n**{player_b}**: `{s2['wins']}` 胜\n(平: {draws})",
        inline=True
    )
    
    # 2. 直击 PT 差
    diff = data['p1_pt_diff']
    sign = "+" if diff > 0 else ""
    embed.add_field(
        name="Head-to-Head Score",
        value=f"**{player_a}** 对 B:\n`{sign}{diff:.1f}` pts",
        inline=True
    )
    
    # 3. 💥 关键数据：碾压统计 (分两列显示)
    # A 的碾压数据
    stomp_text_a = (
        f"**大胜** (+2): `{s1['big_wins']}` 次\n"
        f"**踩头** (+3): `{s1['stomps']}` 次"
    )
    embed.add_field(name=f"🟦 {player_a} 战绩详情", value=stomp_text_a, inline=False)

    # B 的碾压数据
    stomp_text_b = (
        f"**大胜** (+2): `{s2['big_wins']}` 次\n"
        f"**踩头** (+3): `{s2['stomps']}` 次"
    )
    embed.add_field(name=f"🟥 {player_b} 战绩详情", value=stomp_text_b, inline=False)
    
    # 4. 统治力进度条
    embed.add_field(
        name="⚖️ 统治力 (基于积分权重)",
        value=f"{bar_str}\n`{rate_a:.1f}%` ◀── 积分占比 ──▶ `{rate_b:.1f}%`",
        inline=False
    )
    
    recent_str = " -> ".join(data["recent_record"])
    embed.set_footer(text=f"最近5场胜者: {recent_str}")

    await interaction.followup.send(embed=embed)
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
@client.tree.command(name="record_game", description="录入成绩并显示变动 (自动等待Sheet计算)")
@app_commands.describe(
    rank1_name="第1名名字", rank1_score="第1名分数",
    rank2_name="第2名名字", rank2_score="第2名分数",
    rank3_name="第3名名字", rank3_score="第3名分数",
    rank4_name="第4名名字", rank4_score="第4名分数",
    manual_time="可选: 手动输入时间 (格式 e.g. 10/24 20:00)，留空则为当前时间"
)
@app_commands.autocomplete(
    rank1_name=player_name_autocomplete, rank2_name=player_name_autocomplete,
    rank3_name=player_name_autocomplete, rank4_name=player_name_autocomplete
)
async def record_game(
    interaction: discord.Interaction, 
    rank1_name: str, rank1_score: int,
    rank2_name: str, rank2_score: int,
    rank3_name: str, rank3_score: int,
    rank4_name: str, rank4_score: int,
    manual_time: str = None 
):
    # 1. 先告诉用户我们在处理
    await interaction.response.defer()
    
    # 检查输入有效性
    players_ordered = [rank1_name, rank2_name, rank3_name, rank4_name]
    scores_ordered = [rank1_score, rank2_score, rank3_score, rank4_score]
    
    # 简单的校验
    if len(set(players_ordered)) != 4:
        await interaction.followup.send("❌ 名字重复！请检查输入。")
        return
    if sum(scores_ordered) != 100000:
        await interaction.followup.send(f"⚠️ 总分异常: {sum(scores_ordered)} (应为100000)，请检查后重新录入。")
        return 

    try:
        # --- 🕒 准备时间戳 ---
        if manual_time:
            final_time_str = manual_time
        else:
            # ✅ 新写法：获取带时区的 UTC 时间
            current_utc = datetime.now(timezone.utc)
            
            # 计算 UTC-8 (西八区)
            # 注意：因为 current_utc 是带时区的，减去 8 小时后它依然带时区信息，更加严谨
            local_time = current_utc - timedelta(hours=8)
            
            # 格式化为字符串 (去掉时区信息只留文字，保持你原有的格式)
            final_time_str = local_time.strftime("%Y-%m-%d %H:%M:%S")

        # --- 📸 阶段一：获取“变动前”状态 ---
        status_msg = await interaction.followup.send("⏳ 正在读取当前排名...", wait=True)
        pre_status = get_players_status(players_ordered)
        
        # --- 📝 阶段二：写入数据 ---
        await status_msg.edit(content="📝 正在写入表格 (优先记录时间)...")
        
        sh = gc.open_by_key(SHEET_ID)
        
        # 👉 动作 A: 先写入 Games/pt (时间表)
        ws_pt = sh.worksheet("Games/pt")
        ws_pt.append_row([final_time_str]) 
        
        # 👉 动作 B: 再写入 Games Riichi (分数表)
        ws_riichi = sh.worksheet("Games Riichi")
        ws_riichi.append_row(players_ordered + scores_ordered)
        
        # --- ⏳ 阶段三：让子弹飞一会儿 ---
        # 等待 Google Sheet 公式计算
        await status_msg.edit(content=f"🔄 数据已写入 (时间: {final_time_str})，等待 Google Sheet 计算 (约1分钟)...")
        await asyncio.sleep(60) 
        
        # --- 📸 阶段四：获取“变动后”状态 ---
        post_status = get_players_status(players_ordered)
        
        # --- 📊 阶段五：生成精美战报 ---
        embed = discord.Embed(title="✅ 结算完成 (Game Summary)", color=0x00FF00)
        embed.description = f"**Time Recorded:** {final_time_str}"
        
        rank_emojis = ["🐶", "🥈", "🥉", "🪦"]
        
        # --- 🛡️ 定义安全转换函数 (防止 str-int 报错) ---
        def safe_float(value):
            try:
                return float(str(value).strip())
            except (ValueError, TypeError):
                return 0.0

        def safe_int(value):
            try:
                return int(float(str(value).strip()))
            except (ValueError, TypeError):
                return 999 

        # --- 🔄 遍历每个玩家生成数据 ---
        for i, name in enumerate(players_ordered):
            score = scores_ordered[i]
            
            # 取出该玩家的前后数据 (没有则为空字典)
            pre = pre_status.get(name, {})
            post = post_status.get(name, {})
            
            # ==============================
            # 1. MMR 部分 (积分)
            # ==============================
            post_mmr = safe_float(post.get('mmr', 0))
            pre_mmr = safe_float(pre.get('mmr', 0))
            
            mmr_diff = post_mmr - pre_mmr
            mmr_sign = "+" if mmr_diff >= 0 else ""
            mmr_str = f"{post_mmr:.1f} ({mmr_sign}{mmr_diff:.1f})"
            
            # MMR 排名
            pre_mmr_rank = safe_int(pre.get('mmr_rank', 999))
            post_mmr_rank = safe_int(post.get('mmr_rank', 999))
            
            r_diff = pre_mmr_rank - post_mmr_rank 
            if r_diff > 0: r_icon = f"🔺{r_diff}" 
            elif r_diff < 0: r_icon = f"🔻{abs(r_diff)}" 
            else: r_icon = "➖"
            
            disp_mmr_rank = post_mmr_rank if post_mmr_rank != 999 else "??"
            mmr_rank_str = f"Rank: #{disp_mmr_rank} ({r_icon})"

            # ==============================
            # 2. PT 部分 (点数)
            # ==============================
            post_pt = safe_float(post.get('pt', 0))
            pre_pt = safe_float(pre.get('pt', 0))
            
            pt_diff = post_pt - pre_pt
            pt_sign = "+" if pt_diff >= 0 else ""
            pt_str = f"{post_pt:.1f} ({pt_sign}{pt_diff:.1f})"
            
            # PT 排名
            pre_pt_rank = safe_int(pre.get('pt_rank', 999))
            post_pt_rank = safe_int(post.get('pt_rank', 999))
            
            p_r_diff = pre_pt_rank - post_pt_rank
            if p_r_diff > 0: p_r_icon = f"🔺{p_r_diff}" 
            elif p_r_diff < 0: p_r_icon = f"🔻{abs(p_r_diff)}" 
            else: p_r_icon = "➖"
            
            disp_pt_rank = post_pt_rank if post_pt_rank != 999 else "??"
            pt_rank_str = f"Rank: #{disp_pt_rank} ({p_r_icon})"

            # ==============================
            # 3. 组合显示的文本
            # ==============================
            field_val = (
                f" **MMR**: `{mmr_str}` | {mmr_rank_str}\n"
                f" **PT**: `{pt_str}` | {pt_rank_str}"
            )
            
            embed.add_field(
                name=f"{rank_emojis[i]} {name} ({score})",
                value=field_val,
                inline=False
            )

        # 发送最终战报
        await status_msg.edit(content="", embed=embed)

    except Exception as e:
        # 错误处理：打印堆栈并通知用户
        import traceback
        traceback.print_exc()
        
        error_text = f"❌ 发生了未知错误: {str(e)}"
        if 'status_msg' in locals():
            await status_msg.edit(content=error_text)
        else:
            await interaction.followup.send(error_text)
# main.py

# 确保你在开头导入了 SeatSelectView
from mahjong_ui import SeatSelectView 

# ... (其他的 import 和代码) ...

@client.tree.command(name="record", description="开始记录一局麻将 (Start Recording)")
@app_commands.describe(player_name="选择记录的玩家名字")
@app_commands.autocomplete(player_name=player_name_autocomplete) # <--- 复用你的自动补全！
async def record(interaction: discord.Interaction, player_name: str):
    # 1. 创建 View
    # 注意：这里传入 interaction.user.id，防止别人乱点你的按钮
    view = SeatSelectView(player_name, interaction.user.id)
    
    # 2. 发送消息
    # Slash Command 必须用 interaction.response
    await interaction.response.send_message(
        content=f"👋 你好 **{player_name}**，请选择你的起家位置：", 
        view=view,
        ephemeral=False # 设为 False 让大家都能看到这局开始了，设为 True 则只有你能看见
    )

@client.tree.command(name="report", description="生成战报 (周/月/Quarter)")
@app_commands.describe(period="选择统计周期")
@app_commands.choices(period=[
    app_commands.Choice(name="📅 Weekly (本周)", value="weekly"),
    app_commands.Choice(name="🌙 Monthly (本月)", value="monthly"),
    app_commands.Choice(name="❄️ Quarter (本季度)", value="quarter") 
])
async def report(interaction: discord.Interaction, period: app_commands.Choice[str]):
    await interaction.response.defer()
    
    try:
        now = datetime.datetime.now()
        start_date = None
        end_date = None
        title = ""
        
        # --- 1. 确定时间范围 ---
        if period.value == "weekly":
            start_date = now - datetime.timedelta(days=7)
            title = "Weekly Report (近7天)"
            
        elif period.value == "monthly":
            start_date = now - datetime.timedelta(days=30)
            title = "Monthly Report (近30天)"
            
        elif period.value == "quarter":
            # 读取 Quarter 配置
            config = get_quarter_config()
            if not config or not config["start"]:
                await interaction.followup.send("⚠️ 管理员尚未设置本 Quarter 时间。请让管理员使用 `/set_quarter`。")
                return
            
            start_date = config["start"]
            end_date = config["end"]
            title = "Quarter Report (本季度)"

        # --- 2. 获取数据 (这里是你修改过的地方，现在是对的) ---
        acc_stats = get_accumulated_stats(start_date, end_date)
        
        # --- 3. 获取当前 MMR (用于展示在面板上) ---
        # ⚠️ 确保你之前定义过 get_players_status 函数
        current_status = get_players_status(list(acc_stats.keys()))
        
        # --- 4. 生成漂亮的 Embed (这是你漏掉的部分) ---
        embed = discord.Embed(title=f"📊 {title}", color=0x00BFFF)
        
        # 按 PT 从高到低排序
        sorted_players = sorted(acc_stats.items(), key=lambda x: x[1]['pt'], reverse=True)
        
        if not sorted_players:
            embed.description = "❌ 该时间段内没有对局记录。"
        else:
            for rank, (name, data) in enumerate(sorted_players, 1):
                pt_gain = data['pt']
                games = data['games']
                
                # 格式化 PT (+号)
                pt_str = f"+{pt_gain:.1f}" if pt_gain > 0 else f"{pt_gain:.1f}"
                
                # 获取该玩家当前的 MMR
                curr_mmr = current_status.get(name, {}).get('mmr', 'N/A')
                
                # 排名图标
                emoji = "🥇" if rank==1 else "🥈" if rank==2 else "🥉" if rank==3 else f"`#{rank}`"
                
                embed.add_field(
                    name=f"{emoji} {name.title()}",
                    value=f" PT: `{pt_str}` |  `{games}` 场\n MMR: `{curr_mmr}`",
                    inline=False
                )
        
        # --- 5. 设置底部时间并发送 ---
        time_str = start_date.strftime("%Y/%m/%d")
        if end_date:
            time_str += f" - {end_date.strftime('%Y/%m/%d')}"
        else:
            time_str += " - 至今"
            
        embed.set_footer(text=f"统计区间: {time_str}")
        
        await interaction.followup.send(embed=embed)

    except Exception as e:
        # 如果出错了，打印出来并告诉用户
        print(f"Report Error: {e}")
        await interaction.followup.send(f"❌ 战报生成失败: {str(e)}")
    
    # ... 发送 ...
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
        result_msg = await asyncio.to_thread(perform_google_sheet_registration, new_name)
        if "成功" in result_msg:            
            # 只有当本地列表里还没有这个名字时才添加 (双重保险)
            if new_name not in PLAYER_NAME_CACHE:
                PLAYER_NAME_CACHE.append(new_name)
                print(f"✅ 本地缓存已手动追加: {new_name}")
            
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
        
        # append_row 会自动寻找表格最底部的空行写入，非常方便且安全
        ws.append_row(new_row)
        
        return f"注册成功！欢迎 **{player_name}** 加入。初始分数: 1500"
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