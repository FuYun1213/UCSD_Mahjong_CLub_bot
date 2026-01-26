import discord
from discord.ui import View, Button, Select, Modal, TextInput
import pandas as pd
import os
from datetime import datetime

# ==========================================
# 0. 配置与役种数据
# ==========================================
DATA_FILE = 'mahjong_records.csv'

# 【改动1】从这里移除了 宝牌、赤宝牌、里宝牌，因为我们要用数字输入
YAKU_1_HAN = [
    ("立直 (Riichi)", "立直"), ("一发 (Ippatsu)", "一发"), ("门前清自摸 (Menzen Tsumo)", "门前清自摸"),
    ("断幺九 (Tanyao)", "断幺九"), ("平和 (Pinfu)", "平和"), ("一帕口 (Iipeiko)", "一帕口"),
    ("役牌: 白 (Yakuhai: White)", "役牌:白"), ("役牌: 发 (Yakuhai: Green)", "役牌:发"), ("役牌: 中 (Yakuhai: Red)", "役牌:中"),
    ("役牌: 场风 (Seat Wind)", "役牌:场风"), ("役牌: 自风 (Prevalent Wind)", "役牌:自风"),
    ("岭上开花 (Rinshan)", "岭上开花"), ("抢杠 (Chankan)", "抢杠"), ("海底/河底 (Haitei/Houtei)", "海底/河底")
]

YAKU_2_HAN = [
    ("三色同顺 (Sanshoku Doujun)", "三色同顺"), ("一气通贯 (Itsu)", "一气通贯"), ("混全带幺九 (Chanta)", "混全带幺九"),
    ("七对子 (Chiitoitsu)", "七对子"), ("对对和 (Toitoi)", "对对和"), ("三暗刻 (San Ankou)", "三暗刻"),
    ("三色同刻 (Sanshoku Doukou)", "三色同刻"), ("三杠子 (San Kantsu)", "三杠子"), 
    ("小三元 (Shousangen)", "小三元"), ("混老头 (Honroutou)", "混老头")
]

YAKU_HIGH = [
    ("二帕口 (Ryanpeiko)", "二帕口"), ("混一色 (Honitsu)", "混一色"), ("纯全带幺九 (Junchan)", "纯全带幺九"),
    ("清一色 (Chinitsu)", "清一色"), 
    ("国士无双 (Kokushi)", "国士无双"), ("四暗刻 (Suu Ankou)", "四暗刻"), ("大三元 (Dai Sangen)", "大三元"),
    ("字一色 (Tsuuiisou)", "字一色"), ("小四喜 (Shousuushii)", "小四喜"), ("大四喜 (Dai Suushii)", "大四喜"),
    ("绿一色 (Ryuuiisou)", "绿一色"), ("清老头 (Chinroutou)", "清老头"), ("四杠子 (Suu Kantsu)", "四杠子"),
    ("九莲宝灯 (Chuuren Poutou)", "九莲宝灯"), ("天和/地和 (Tenhou/Chiihou)", "天和/地和")
]

def save_record(record_dict):
    """保存数据到 CSV"""
    df_new = pd.DataFrame([record_dict])
    if not os.path.exists(DATA_FILE):
        df_new.to_csv(DATA_FILE, index=False, encoding='utf-8-sig')
    else:
        df_new.to_csv(DATA_FILE, mode='a', header=False, index=False, encoding='utf-8-sig')

# ==========================================
# 1. 【核心改动】最终确认点数的弹窗
# ==========================================
class FinalScoreModal(Modal):
    def __init__(self, parent_view, selected_yaku):
        super().__init__(title="和牌结算 (Win Settlement)")
        self.parent_view = parent_view 
        self.selected_yaku = selected_yaku 
        
        # 1. 点数 (必填)
        self.points_input = TextInput(
            label="和牌点数 (Score)", 
            placeholder="例如: 8000", 
            required=True,
            max_length=6
        )
        self.add_item(self.points_input)

        # 2. 宝牌数量 (选填)
        self.dora_input = TextInput(
            label="宝牌数 (Dora Count)", 
            placeholder="输入张数 (0-13)", 
            required=False, 
            default="0",
            max_length=2
        )
        self.add_item(self.dora_input)

        # 3. 赤宝牌数量 (选填)
        self.aka_input = TextInput(
            label="赤宝牌数 (Red Dora Count)", 
            placeholder="输入张数 (0-3)", 
            required=False, 
            default="0",
            max_length=1
        )
        self.add_item(self.aka_input)

        # 4. 里宝牌数量 (选填)
        self.ura_input = TextInput(
            label="里宝牌数 (Ura Dora Count)", 
            placeholder="输入张数 (立直后可选)", 
            required=False, 
            default="0",
            max_length=2
        )
        self.add_item(self.ura_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            points = int(self.points_input.value)
            
            # --- 处理 Dora 数量 ---
            # 如果输入为空或者非数字，默认为 0
            dora_count = int(self.dora_input.value) if self.dora_input.value.isdigit() else 0
            aka_count = int(self.aka_input.value) if self.aka_input.value.isdigit() else 0
            ura_count = int(self.ura_input.value) if self.ura_input.value.isdigit() else 0
            
            # 将 Dora 信息添加到役种列表里
            final_yaku_list = self.selected_yaku.copy()
            if dora_count > 0: final_yaku_list.append(f"宝牌x{dora_count}")
            if aka_count > 0: final_yaku_list.append(f"赤宝牌x{aka_count}")
            if ura_count > 0: final_yaku_list.append(f"里宝牌x{ura_count}")
            
            yaku_str = ", ".join(final_yaku_list) if final_yaku_list else "无役/Only Dora"
            
            await self.parent_view.origin_view.record_win(
                interaction, points, yaku_str
            )
        except ValueError:
            await interaction.response.send_message("❌ 错误：请输入有效的数字！", ephemeral=True)

# ==========================================
# 2. 役种选择界面 (View)
# ==========================================
class YakuSelectView(View):
    def __init__(self, origin_view):
        super().__init__(timeout=300)
        self.origin_view = origin_view 
        self.selected_yaku = [] 
        
        # Dora 现在不在菜单里了，菜单只用来选“名字”
        self.add_yaku_select(YAKU_1_HAN, "1番 (Dora在下一步填)...", 1)
        self.add_yaku_select(YAKU_2_HAN, "2番/3番 (可多选)...", 2)
        self.add_yaku_select(YAKU_HIGH, "满贯/役满 (可多选)...", 3)

    def add_yaku_select(self, yaku_list, placeholder, row):
        options = [discord.SelectOption(label=name, value=val) for name, val in yaku_list]
        select = Select(placeholder=placeholder, options=options, min_values=0, max_values=len(options), row=row)
        select.callback = self.yaku_callback
        self.add_item(select)

    async def yaku_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

    @discord.ui.button(label="下一步: 输入点数 & Dora", style=discord.ButtonStyle.success, row=4)
    async def confirm_btn(self, interaction: discord.Interaction, button: Button):
        self.selected_yaku = []
        for child in self.children:
            if isinstance(child, Select) and child.values:
                self.selected_yaku.extend(child.values)
        
        # 弹出包含 Dora 输入框的 Modal
        await interaction.response.send_modal(FinalScoreModal(self, self.selected_yaku))

# ==========================================
# 3. 普通点数弹窗 (点炮/自摸用)
# ==========================================
class SimplePointsModal(Modal):
    def __init__(self, title, action_type, session_view):
        super().__init__(title=title)
        self.action_type = action_type
        self.session_view = session_view
        self.points_input = TextInput(label="点数变动 (例如: -5200)", placeholder="输入数字", required=True)
        self.add_item(self.points_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            points = int(self.points_input.value)
            await self.session_view.record_action(interaction, self.action_type, points, "N/A")
        except ValueError:
            await interaction.response.send_message("❌ 请输入有效的数字！", ephemeral=True)

# ==========================================
# 4. 游戏主控制面板 (增加副露状态)
# ==========================================
class GameSessionView(View):
    def __init__(self, player_name, seat, user_id):
        super().__init__(timeout=3600)
        self.player_name = player_name
        self.seat = seat
        self.user_id = user_id
        
        self.round_wind = "东"
        self.round_num = 1
        self.honba = 0
        self.riichi_status = False 
        self.is_open_hand = False  # 副露状态
        
        self.update_buttons()

    def get_round_name(self):
        return f"{self.round_wind}{self.round_num}局 {self.honba}本场"

    def update_buttons(self):
        self.clear_items()
        
        # Row 0: 状态
        riichi_btn = Button(
            label="立直 (Riichi)" if not self.riichi_status else "立直中 (Riichi ON)", 
            style=discord.ButtonStyle.danger if self.riichi_status else discord.ButtonStyle.secondary, 
            row=0
        )
        riichi_btn.callback = self.toggle_riichi
        self.add_item(riichi_btn)

        open_btn = Button(
            label="门清 (Closed)" if not self.is_open_hand else "副露 (Open)",
            style=discord.ButtonStyle.primary if self.is_open_hand else discord.ButtonStyle.secondary,
            row=0
        )
        open_btn.callback = self.toggle_open
        self.add_item(open_btn)

        # Row 1: 动作
        btn_win = Button(label="和牌 (Win)", style=discord.ButtonStyle.success, row=1)
        btn_win.callback = self.action_win_step1
        self.add_item(btn_win)

        btn_deal_in = Button(label="点炮 (Deal-in)", style=discord.ButtonStyle.danger, row=1)
        btn_deal_in.callback = self.action_deal_in
        self.add_item(btn_deal_in)
        
        btn_tsumo_d = Button(label="被自摸 (Tsumo-ed)", style=discord.ButtonStyle.danger, row=1)
        btn_tsumo_d.callback = self.action_tsumo_d
        self.add_item(btn_tsumo_d)

        # Row 2: 流局
        select_tenpai = Select(placeholder="听牌/流局结算...", options=[
            discord.SelectOption(label="听牌 +3000", value="3000"),
            discord.SelectOption(label="听牌 +1500", value="1500"),
            discord.SelectOption(label="听牌 +1000", value="1000"),
            discord.SelectOption(label="听牌 +0", value="0"),
            discord.SelectOption(label="流局 -0", value="-0"),
            discord.SelectOption(label="流局 -1000", value="-1000"),
            discord.SelectOption(label="流局 -1500", value="-1500"),
            discord.SelectOption(label="流局 -3000", value="-3000"),
        ], row=2)
        select_tenpai.callback = self.action_draw_select
        self.add_item(select_tenpai)

        # Row 3: 流转
        btn_renchan = Button(label="连庄 (Renchan)", style=discord.ButtonStyle.primary, row=3)
        btn_renchan.callback = self.next_renchan
        self.add_item(btn_renchan)

        btn_next = Button(label="下家/下一局 (Next)", style=discord.ButtonStyle.secondary, row=3)
        btn_next.callback = self.next_round_normal
        self.add_item(btn_next)
        
        btn_stop = Button(label="End", style=discord.ButtonStyle.grey, row=3)
        btn_stop.callback = self.stop_session
        self.add_item(btn_stop)

    # --- Callbacks ---
    async def toggle_riichi(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return
        self.riichi_status = not self.riichi_status
        if self.riichi_status: self.is_open_hand = False 
        self.update_buttons()
        await interaction.response.edit_message(view=self)

    async def toggle_open(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return
        self.is_open_hand = not self.is_open_hand
        if self.is_open_hand: self.riichi_status = False
        self.update_buttons()
        await interaction.response.edit_message(view=self)

    async def action_win_step1(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return
        await interaction.response.send_message(
            "🀄 **请选择役种:**\nDora 数量将在下一步输入。",
            view=YakuSelectView(origin_view=self),
            ephemeral=True
        )

    async def record_win(self, interaction, points, yaku_str):
        await self.record_action(interaction, "和牌", points, yaku_str)

    async def action_deal_in(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return
        await interaction.response.send_modal(SimplePointsModal("点炮结算", "点炮", self))
        
    async def action_tsumo_d(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return
        await interaction.response.send_modal(SimplePointsModal("被自摸结算", "被自摸", self))

    async def action_draw_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return
        val = int(interaction.data['values'][0])
        action = "听牌" if val >= 0 else "流局"
        await self.record_action(interaction, action, val, "流局/听牌")

    async def record_action(self, interaction, action_type, points, details):
        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "player": self.player_name,
            "seat": self.seat,
            "round": self.get_round_name(),
            "action": action_type,
            "is_riichi": self.riichi_status,
            "is_open": self.is_open_hand,
            "points": points,
            "details": details
        }
        await save_record(record)
        
        desc = f"**{action_type}** | **{points}**点"
        if details != "N/A" and details != "流局/听牌":
            desc += f"\n役种: {details}"
        
        status_text = []
        if self.riichi_status: status_text.append("🔴立直")
        if self.is_open_hand: status_text.append("👐副露")
        else: status_text.append("🚪门清")
        
        embed = discord.Embed(title=f"✅ 记录: {self.get_round_name()}", description=desc, color=discord.Color.green())
        embed.set_footer(text=" | ".join(status_text))
        
        if not interaction.response.is_done():
             await interaction.response.edit_message(embed=embed, view=self)
        else:
             await interaction.response.send_message(embed=embed, ephemeral=True)

    async def next_renchan(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return
        self.honba += 1
        self.riichi_status = False 
        self.is_open_hand = False
        self.update_buttons()
        await interaction.response.edit_message(content=f"当前状态: **{self.player_name}** | {self.get_round_name()}", view=self, embed=None)

    async def next_round_normal(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return
        self.honba = 0
        self.riichi_status = False
        self.is_open_hand = False
        self.round_num += 1
        if self.round_num > 4:
            if self.round_wind == "东":
                self.round_wind = "南"
                self.round_num = 1
            elif self.round_wind == "南":
                self.round_wind = "西"
                self.round_num = 1
        self.update_buttons()
        await interaction.response.edit_message(content=f"当前状态: **{self.player_name}** | {self.get_round_name()}", view=self, embed=None)

    async def stop_session(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: return
        await interaction.response.edit_message(content="🛑 记录结束。", view=None, embed=None)
        self.stop()

class SeatSelectView(View):
    def __init__(self, player_name, user_id):
        super().__init__()
        self.player_name = player_name
        self.user_id = user_id

    @discord.ui.select(placeholder="请选择你的起家位置...", options=[
        discord.SelectOption(label="东 (East)", value="东"),
        discord.SelectOption(label="南 (South)", value="南"),
        discord.SelectOption(label="西 (West)", value="西"),
        discord.SelectOption(label="北 (North)", value="北"),
    ])
    async def select_seat(self, interaction: discord.Interaction, select: Select):
        if interaction.user.id != self.user_id: return
        seat = select.values[0]
        game_view = GameSessionView(self.player_name, seat, self.user_id)
        await interaction.response.edit_message(
            content=f"🎮 开始记录: **{self.player_name}** \n起家: {seat}\n当前: {game_view.get_round_name()}",
            view=game_view
        )