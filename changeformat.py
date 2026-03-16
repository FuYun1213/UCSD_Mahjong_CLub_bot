import pandas as pd

def process_2024_fall(input_file, output_file):
    try:
        # 读取文件
        df = pd.read_csv(input_file, header=None)
    except FileNotFoundError:
        print(f"找不到文件: {input_file}")
        return

    # --- 关键配置 (针对2024 Fall文件结构) ---
    date_row_idx = 0       # 日期在第1行 (索引0)
    game_row_idx = 1       # 局数在第2行 (索引1)
    data_start_row_idx = 2 # 玩家数据从第3行开始 (索引2)
    start_col = 9          # 数据从第10列 (J列) 开始

    # --- 1. 获取日期和局数行 ---
    dates_row = df.iloc[date_row_idx]
    games_row = df.iloc[game_row_idx]

    # --- 2. 填充日期 ---
    dates = []
    current_date = ""
    for val in dates_row:
        if pd.notna(val) and isinstance(val, str):
            current_date = val
        dates.append(current_date)

    game_records = []

    # --- 3. 遍历每一局 ---
    for j in range(start_col, df.shape[1], 3):
        if j + 2 >= df.shape[1]:
            break
            
        date = dates[j]
        game_id = games_row[j]
        
        # 跳过无效列
        if pd.isna(game_id):
            continue
            
        # --- 4. 提取玩家 ---
        players = []
        for i in range(data_start_row_idx, df.shape[0]):
            name = df.iloc[i, 0]    # 名字在第1列
            score = df.iloc[i, j]   # 分数
            rank = df.iloc[i, j+2]  # 排名
            
            if pd.notna(score):
                try:
                    rank_val = float(rank)
                except:
                    rank_val = 999
                
                players.append({
                    'Name': name,
                    'Score': score,
                    'Rank': rank_val
                })
        
        # --- 5. 排序并保存 ---
        if players:
            players.sort(key=lambda x: x['Rank'])
            
            record = {'日期': date, '局数': game_id}
            
            for k in range(4):
                if k < len(players):
                    record[f'玩家{k+1}'] = players[k]['Name']
                    # 处理分数格式 (去掉 .0)
                    s_val = players[k]['Score']
                    try:
                        s_val = str(int(float(s_val)))
                    except:
                        pass
                    record[f'玩家{k+1}分数'] = s_val
                else:
                    record[f'玩家{k+1}'] = ''
                    record[f'玩家{k+1}分数'] = ''
                    
            game_records.append(record)

    # --- 6. 导出 ---
    if game_records:
        result_df = pd.DataFrame(game_records)
        result_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"成功！文件已保存为: {output_file}")
    else:
        print("未提取到数据，请检查文件格式。")

# --- 请修改这里的文件名 ---
input_filename = '2024积分表 - 2024 fall（副本） (1).csv'
output_filename = '2024_Fall_Restructured.csv'

process_2024_fall(input_filename, output_filename)