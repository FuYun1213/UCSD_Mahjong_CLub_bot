import discord
from discord import app_commands
from discord.ext import commands
import gspread

# ==========================================
# ⚙️ Google Sheets 配置
# ==========================================
SHEET_ID = '1Ce5k2Blbf5MYXbM4rSTeWHOf2uTHPrvZX6vm6Cdyc5Q'  
CREDENTIALS_FILE = 'credentials.json'

class QuarterUpdate(commands.Cog):
    def __init__(self, client):
        self.client = client
        # 初始化 Google Sheets 客户端
        try:
            self.gc = gspread.service_account(filename=CREDENTIALS_FILE)
            self.sh = self.gc.open_by_key(SHEET_ID)
        except Exception as e:
            print(f"❌ Admin Cog: Google Sheets 连接失败: {e}")
            self.gc = None

    @app_commands.command(name="quarter_end", description="[Admin Only] 赛季结算与表格更新")
    @app_commands.describe(
        current_quarter="当前赛季名字 (如: 2024Q1)",
        next_quarter="下个赛季名字 (如: 2024Q2)"
    )
    # ✅ 权限控制：只有 Discord 服务器管理员可用
    @app_commands.default_permissions(administrator=True) 
    async def quarter_end(self, interaction: discord.Interaction, current_quarter: str, next_quarter: str):
        if self.gc is None:
            await interaction.response.send_message("❌ Google Sheets 未连接，请检查后台报错。", ephemeral=True)
            return

        # 耗时操作，先 defer
        await interaction.response.defer(ephemeral=True)

        try:
            # ---------------------------------------------------------
            # 1. 复制并重命名表格 (Duplicate and Rename Sheets)
            # ---------------------------------------------------------
            ws_ranking = self.sh.worksheet("Ranking Quarter")
            ws_personal = self.sh.worksheet("Personal Data Quarter")

            # 复制表格 (如果已存在同名表格会报错，我们用 try-except 捕获)
            try:
                self.sh.duplicate_sheet(ws_ranking.id, new_sheet_name=f"{current_quarter} Ranking")
                self.sh.duplicate_sheet(ws_personal.id, new_sheet_name=f"{current_quarter} Personal Data")
            except Exception as e:
                if "already exists" in str(e).lower():
                    await interaction.followup.send(f"⚠️ 警告: `{current_quarter}` 相关的备份表格已经存在，无法重复复制！")
                    return
                raise e

            # ---------------------------------------------------------
            # 2. 找到 'Games/pt' 的空行并打上新赛季标记 (Find empty row & mark)
            # 注意: 你的公式里写的是 'Games/pt'，如果表名叫 'Games Riichi' 请修改这里
            # ---------------------------------------------------------
            ws_games = self.sh.worksheet("Games/pt")
            
            # 获取所有数据，找到第一行空行的行号
            all_values = ws_games.get_all_values()
            new_row = len(all_values) + 1 

            # 在第 R 列 (第 18 列) 记录 Next Quarter 的名字
            ws_games.update_cell(new_row, 18, next_quarter)

            # ---------------------------------------------------------
            # 3. 更新 'Personal Data Quarter all name' 里的公式
            # ---------------------------------------------------------
            ws_target = self.sh.worksheet("Personal Data Quarter all name")

            # 注意：Google Sheets公式里的 {} 在 Python f-string 中需要写成 {{}}
            f_C2 = f'=ARRAYFORMULA( IF(A2:A="",, SUMIF(\'Games/pt\'!B{new_row}:B, A2:A, \'Games/pt\'!D{new_row}:D) + SUMIF(\'Games/pt\'!E{new_row}:E, A2:A, \'Games/pt\'!G{new_row}:G) + SUMIF(\'Games/pt\'!H{new_row}:H, A2:A, \'Games/pt\'!J{new_row}:J) + SUMIF(\'Games/pt\'!K{new_row}:K, A2:A, \'Games/pt\'!M{new_row}:M) + \'Games/pt\'!T2 ) )'
            
            f_F2 = f'=MAP(A2:A, LAMBDA(name, IF(name="",, IFERROR( MAX( FILTER( {{\'Games/pt\'!C{new_row}:C;\'Games/pt\'!F{new_row}:F;\'Games/pt\'!I{new_row}:I;\'Games/pt\'!L{new_row}:L}}, {{\'Games/pt\'!B{new_row}:B;\'Games/pt\'!E{new_row}:E;\'Games/pt\'!H{new_row}:H;\'Games/pt\'!K{new_row}:K}}=name ) ), 0 ) ) ))'
            
            f_G2 = f'=MAP(A2:A, LAMBDA(name, IF(name="",, IFERROR( AVERAGE( FILTER( {{\'Games/pt\'!C{new_row}:C;\'Games/pt\'!F{new_row}:F;\'Games/pt\'!I{new_row}:I;\'Games/pt\'!L{new_row}:L}}, {{\'Games/pt\'!B{new_row}:B;\'Games/pt\'!E{new_row}:E;\'Games/pt\'!H{new_row}:H;\'Games/pt\'!K{new_row}:K}}=name ) ), 0 ) ) ))'
            
            f_L2 = f'=ARRAYFORMULA( IF(A2:A="",, COUNTIF(\'Games/pt\'!B{new_row}:B, A2:A) ) )'
            f_M2 = f'=ARRAYFORMULA( IF(A2:A="",, COUNTIF(\'Games/pt\'!E{new_row}:E, A2:A) ) )'
            f_N2 = f'=ARRAYFORMULA( IF(A2:A="",, COUNTIF(\'Games/pt\'!H{new_row}:H, A2:A) ) )'
            f_O2 = f'=ARRAYFORMULA( IF(A2:A="",, COUNTIF(\'Games/pt\'!K{new_row}:K, A2:A) ) )'

            # 批量更新公式，避免请求次数过多导致限速
            update_data = [
                {'range': 'C2', 'values': [[f_C2]]},
                {'range': 'F2', 'values': [[f_F2]]},
                {'range': 'G2', 'values': [[f_G2]]},
                {'range': 'L2', 'values': [[f_L2]]},
                {'range': 'M2', 'values': [[f_M2]]},
                {'range': 'N2', 'values': [[f_N2]]},
                {'range': 'O2', 'values': [[f_O2]]},
            ]
            ws_target.batch_update(update_data, value_input_option='USER_ENTERED')

            # ---------------------------------------------------------
            # 4. 发送成功消息
            # ---------------------------------------------------------
            embed = discord.Embed(title="✅ 赛季结算完成 (Quarter End Successful)", color=discord.Color.green())
            embed.add_field(name="1. 表格备份", value=f"已创建:\n- `{current_quarter} Ranking`\n- `{current_quarter} Personal Data`", inline=False)
            embed.add_field(name="2. 赛季标记", value=f"在 `Games/pt` 的第 **{new_row}** 行 R 列 标记了 `{next_quarter}`", inline=False)
            embed.add_field(name="3. 公式更新", value=f"`Personal Data Quarter all name` 中的公式范围已从 759 更新为 **{new_row}**", inline=False)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"❌ 发生严重错误: {e}")


async def setup(client):
    await client.add_cog(QuarterUpdate(client))