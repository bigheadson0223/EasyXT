#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
从QMT补全DuckDB中缺失的A股日线数据

用法：
    python tools/补全duckdb日线数据.py
"""

import os
import sys
import time
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

DUCKDB_PATH = 'D:/StockData/stock_data.ddb'
START_DATE = '20230101'
END_DATE = ''  # 空表示到最新

print("=" * 70)
print("从QMT补全DuckDB日线数据")
print("=" * 70)

# 1. 导入 xtquant
try:
    from xtquant import xtdata
    print("[OK] xtquant 导入成功")
except ImportError as e:
    print(f"[FAIL] xtquant 导入失败: {e}")
    print("请确保 xtquant 已放置在项目根目录下")
    sys.exit(1)

# 2. 导入 duckdb
import duckdb
import pandas as pd

# 3. 获取 DuckDB 中已有的股票列表
con = duckdb.connect(DUCKDB_PATH)
existing_stocks = set(
    con.execute("SELECT DISTINCT stock_code FROM stock_daily").df()['stock_code'].tolist()
)
print(f"[INFO] DuckDB 日线表已有 {len(existing_stocks)} 只股票")

# 4. 从 QMT 获取全量 A 股列表
print("\n[INFO] 从QMT获取A股股票列表...")
try:
    xtdata.download_sector_data()
except Exception as e:
    print(f"[WARN] download_sector_data 失败: {e}")

all_stocks = []
for sector in ['沪深A股', '深证A股', '上证A股']:
    try:
        stocks = xtdata.get_stock_list_in_sector(sector)
        if stocks:
            all_stocks.extend(stocks)
            print(f"  {sector}: {len(stocks)} 只")
    except Exception as e:
        print(f"  {sector}: 获取失败 - {e}")

# 去重
all_stocks = list(set(all_stocks))

# 过滤：只保留标准A股代码（排除指数、基金、债券等）
valid_prefixes_sz = ('000', '001', '002', '003', '300', '301')
valid_prefixes_sh = ('600', '601', '603', '605', '688', '689')
valid_prefixes_bj = ('8', '4')  # 北交所 8xxxxx / 4xxxxx

filtered = []
for s in all_stocks:
    code, mkt = s.split('.') if '.' in s else (s, '')
    if mkt == 'SZ' and code.startswith(valid_prefixes_sz) and len(code) == 6:
        filtered.append(s)
    elif mkt == 'SH' and code.startswith(valid_prefixes_sh) and len(code) == 6:
        filtered.append(s)
    elif mkt == 'BJ' and len(code) == 6:
        filtered.append(s)

all_stocks = sorted(filtered)
print(f"\n[INFO] 有效A股总数: {len(all_stocks)}")

# 5. 找出缺失的股票
missing_stocks = [s for s in all_stocks if s not in existing_stocks]
print(f"[INFO] 缺失股票数: {len(missing_stocks)}")

if not missing_stocks:
    print("\n[OK] 所有A股日线数据已完整，无需补全！")
    con.close()
    sys.exit(0)

# 按市场统计缺失
sh_missing = [s for s in missing_stocks if s.endswith('.SH')]
sz_missing = [s for s in missing_stocks if s.endswith('.SZ')]
bj_missing = [s for s in missing_stocks if s.endswith('.BJ')]
print(f"  上海缺失: {len(sh_missing)}")
print(f"  深圳缺失: {len(sz_missing)}")
print(f"  北京缺失: {len(bj_missing)}")

# 6. 开始下载并写入 DuckDB
print(f"\n开始补全 {len(missing_stocks)} 只股票...")
print("-" * 70)

success_count = 0
fail_count = 0
total_records = 0
start_time = time.time()

for i, stock_code in enumerate(missing_stocks, 1):
    try:
        # 下载数据到 QMT 本地缓存
        xtdata.download_history_data(
            stock_code=stock_code,
            period='1d',
            start_time=START_DATE,
            end_time=END_DATE,
            incrementally=True
        )

        # 从本地缓存读取数据
        # xtdata.get_market_data 返回: {field: DataFrame}
        # 每个 DataFrame 的列是日期字符串，行索引是股票代码
        data = xtdata.get_market_data(
            stock_list=[stock_code],
            period='1d',
            start_time=START_DATE,
            end_time=END_DATE or '',
            count=-1
        )

        if not data or 'time' not in data:
            fail_count += 1
            continue

        # 提取日期列（列名是日期字符串如 '20230101'）
        time_df = data['time']
        if stock_code not in time_df.index:
            fail_count += 1
            continue

        dates = time_df.columns.tolist()
        if not dates:
            fail_count += 1
            continue

        # 构建 DataFrame：每个日期一行
        rows = []
        for date_str in dates:
            try:
                row = {
                    'stock_code': stock_code,
                    'symbol_type': 'stock',
                    'date': pd.Timestamp(date_str),
                    'period': '1d',
                    'open': data['open'].loc[stock_code, date_str] if stock_code in data['open'].index else None,
                    'high': data['high'].loc[stock_code, date_str] if stock_code in data['high'].index else None,
                    'low': data['low'].loc[stock_code, date_str] if stock_code in data['low'].index else None,
                    'close': data['close'].loc[stock_code, date_str] if stock_code in data['close'].index else None,
                    'volume': data['volume'].loc[stock_code, date_str] if stock_code in data['volume'].index else None,
                    'amount': data['amount'].loc[stock_code, date_str] if stock_code in data['amount'].index else None,
                    'adjust_type': 'none',
                    'factor': 1.0,
                    'created_at': pd.Timestamp.now(),
                    'updated_at': pd.Timestamp.now(),
                }
                # 跳过全空行
                if all(v is None for k, v in row.items() if k in ('open', 'high', 'low', 'close')):
                    continue
                rows.append(row)
            except Exception:
                continue

        if not rows:
            fail_count += 1
            continue

        df = pd.DataFrame(rows)

        if df.empty:
            fail_count += 1
            continue

        # 只保留需要的列
        required_cols = ['stock_code', 'symbol_type', 'date', 'period',
                        'open', 'high', 'low', 'close', 'volume', 'amount',
                        'adjust_type', 'factor', 'created_at', 'updated_at']
        for c in required_cols:
            if c not in df.columns:
                df[c] = None
        df = df[required_cols]

        if df.empty:
            fail_count += 1
            continue

        # 删除该股票旧数据后插入
        con.execute(f"DELETE FROM stock_daily WHERE stock_code = '{stock_code}'")
        df.to_sql('stock_daily', con, if_exists='append', index=False, method='multi')

        success_count += 1
        total_records += len(df)

        if i % 20 == 0 or i == len(missing_stocks):
            elapsed = time.time() - start_time
            speed = i / elapsed if elapsed > 0 else 0
            eta = (len(missing_stocks) - i) / speed / 60 if speed > 0 else 0
            print(f"  [{i}/{len(missing_stocks)}] 成功:{success_count} 失败:{fail_count} "
                  f"记录:{total_records:,} 速度:{speed:.1f}只/s 剩余:{eta:.0f}分钟")

        time.sleep(0.05)

    except Exception as e:
        fail_count += 1
        if fail_count <= 5:
            print(f"  {stock_code} 失败: {str(e)[:80]}")

# 7. 结果统计
elapsed = time.time() - start_time
print()
print("=" * 70)
print("补全完成")
print(f"  成功: {success_count}")
print(f"  失败: {fail_count}")
print(f"  新增记录: {total_records:,} 条")
print(f"  耗时: {elapsed/60:.1f} 分钟")

# 8. 验证
final_count = con.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
final_records = con.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
print(f"\n数据库最终状态:")
print(f"  股票数: {final_count}")
print(f"  总记录: {final_records:,}")
print("=" * 70)

con.close()
