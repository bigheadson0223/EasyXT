#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全A股Tick（逐笔）数据批量下载工具

将tick数据下载并保存为Parquet文件，按股票分文件存储。
路径：D:/StockData/raw/tick/{股票代码}.parquet

用法：
    # 默认下载近3个月全A股tick数据
    python tools/download_tick_data.py

    # 测试模式（仅下载000001.SZ）
    python tools/download_tick_data.py --test

    # 指定日期范围
    python tools/download_tick_data.py --start 20250101 --end 20260406

    # 仅下载指定股票
    python tools/download_tick_data.py --stocks 000001.SZ,600000.SH
"""

import os
import sys
import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ===== 配置 =====
OUTPUT_DIR = Path('D:/StockData/raw/tick')
DEFAULT_MONTHS = 3

# QMT tick数据：field_list=[] 表示获取全部字段
# 实际返回列：
#   time, lastPrice, open, high, low, lastClose,
#   amount, volume, pvolume, stockStatus, openInt,
#   lastSettlementPrice, settlementPrice, pe,
#   askPrice(list×5), bidPrice(list×5), askVol(list×5), bidVol(list×5),
#   transactionNum
#
# 五档数据以 list 形式存储在单列中，保存前会拆分为 askPrice1-5 等独立列


def get_all_stock_list(xtdata):
    """获取全量A股列表并过滤为标准股票代码"""
    print("正在获取全部A股股票列表...")

    try:
        xtdata.download_sector_data()
    except Exception as e:
        print(f"  [WARN] download_sector_data 失败: {e}")

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

    # 过滤标准A股代码
    valid_prefixes_sz = ('000', '001', '002', '003', '300', '301')
    valid_prefixes_sh = ('600', '601', '603', '605', '688', '689')

    filtered = []
    for s in all_stocks:
        code, mkt = s.split('.') if '.' in s else (s, '')
        if mkt == 'SZ' and code.startswith(valid_prefixes_sz) and len(code) == 6:
            filtered.append(s)
        elif mkt == 'SH' and code.startswith(valid_prefixes_sh) and len(code) == 6:
            filtered.append(s)

    filtered.sort()
    print(f"有效A股总数: {len(filtered)}")
    return filtered


def download_and_save_tick(xtdata, stock_code, start_date, end_date, output_dir):
    """
    下载单只股票的tick数据并保存为Parquet。

    Args:
        xtdata: xtquant.xtdata 模块
        stock_code: 股票代码，如 '000001.SZ'
        start_date: 开始日期 'YYYYMMDD'
        end_date: 结束日期 'YYYYMMDD'
        output_dir: Parquet输出目录

    Returns:
        (success: bool, record_count: int, error_msg: str)
    """
    import pandas as pd
    import numpy as np

    output_path = output_dir / f"{stock_code}.parquet"

    try:
        # 1. 下载tick数据到QMT本地缓存
        xtdata.download_history_data(
            stock_code=stock_code,
            period='tick',
            start_time=start_date + "000000",
            end_time=end_date + "235959",
        )

        # 2. 从本地缓存读取全部字段（field_list=[] 获取所有列）
        data = xtdata.get_market_data_ex(
            field_list=[],
            stock_list=[stock_code],
            period='tick',
            start_time=start_date,
            end_time=end_date,
            count=-1,
        )

        # 3. 检查返回数据
        if not data or stock_code not in data:
            return False, 0, "get_market_data_ex 返回空"

        df = data[stock_code]
        if df is None or df.empty:
            return False, 0, "DataFrame为空"

        # 4. 时间戳转换：UTC毫秒 → 东八区 TIMESTAMP
        if 'time' not in df.columns:
            return False, 0, "缺少time字段"

        df['time'] = pd.to_datetime(df['time'], unit='ms', utc=True).dt.tz_convert('Asia/Shanghai')
        df.rename(columns={'time': 'timestamp'}, inplace=True)

        # 5. 拆分五档 list 列为独立列（askPrice→askPrice1~5 等）
        for col in ['askPrice', 'bidPrice', 'askVol', 'bidVol']:
            if col in df.columns:
                expanded = pd.DataFrame(df[col].tolist(), index=df.index)
                expanded.columns = [f'{col}{i}' for i in range(1, len(expanded.columns) + 1)]
                df = pd.concat([df.drop(columns=[col]), expanded], axis=1)

        # 6. 添加股票代码列
        df['stock_code'] = stock_code

        # 7. 保存为Parquet（覆盖写入）
        df.to_parquet(output_path, index=False, engine='pyarrow')

        return True, len(df), ""

    except Exception as e:
        return False, 0, str(e)[:120]


def main():
    parser = argparse.ArgumentParser(description='全A股Tick数据批量下载工具')
    parser.add_argument('--start', help='开始日期 (YYYYMMDD)，默认近3个月')
    parser.add_argument('--end', help='结束日期 (YYYYMMDD)，默认今天')
    parser.add_argument('--test', action='store_true', help='测试模式（仅下载000001.SZ）')
    parser.add_argument('--stocks', help='指定股票代码，逗号分隔（如 000001.SZ,600000.SH）')
    parser.add_argument('--output', help=f'输出目录（默认 {OUTPUT_DIR}）')
    parser.add_argument('--skip-existing', action='store_true',
                        help='跳过已存在的Parquet文件')
    args = parser.parse_args()

    # 日期范围
    end_date = args.end or datetime.now().strftime('%Y%m%d')
    if args.start:
        start_date = args.start
    else:
        start_dt = datetime.now() - timedelta(days=DEFAULT_MONTHS * 31)
        start_date = start_dt.strftime('%Y%m%d')

    output_dir = Path(args.output) if args.output else OUTPUT_DIR

    # 打印配置
    print("=" * 70)
    print("全A股Tick数据批量下载工具")
    print("=" * 70)
    print(f"  日期范围: {start_date} ~ {end_date}")
    print(f"  输出目录: {output_dir}")
    print(f"  跳过已有: {'是' if args.skip_existing else '否'}")
    print()

    # 创建输出目录
    output_dir.mkdir(parents=True, exist_ok=True)

    # 导入 xtquant
    try:
        from xtquant import xtdata
        print("[OK] xtquant 导入成功")
    except ImportError as e:
        print(f"[FAIL] xtquant 导入失败: {e}")
        print("请确保 xtquant 已放置在项目根目录下")
        sys.exit(1)

    # 获取股票列表
    if args.test:
        stock_list = ['000001.SZ']
        print(f"测试模式: 仅下载 {stock_list}")
    elif args.stocks:
        stock_list = [s.strip() for s in args.stocks.split(',') if s.strip()]
        print(f"指定下载 {len(stock_list)} 只股票")
    else:
        stock_list = get_all_stock_list(xtdata)

    if not stock_list:
        print("[FAIL] 股票列表为空，退出")
        sys.exit(1)

    total = len(stock_list)
    print(f"\n共 {total} 只股票，开始下载...")
    print("-" * 70)

    # 批量下载
    success_count = 0
    fail_count = 0
    skip_count = 0
    total_records = 0
    total_size = 0
    start_time = time.time()
    errors = []

    for i, code in enumerate(stock_list, 1):
        # 跳过已有文件
        output_path = output_dir / f"{code}.parquet"
        if args.skip_existing and output_path.exists():
            skip_count += 1
            if i % 100 == 0 or i == total:
                elapsed = time.time() - start_time
                speed = i / elapsed if elapsed > 0 else 0
                eta = (total - i) / speed / 60 if speed > 0 else 0
                print(f"  [{i:4d}/{total}] 跳过:{skip_count} 成功:{success_count} "
                      f"失败:{fail_count} 速度:{speed:.1f}只/s 剩余:{eta:.0f}分钟")
            continue

        ok, count, err = download_and_save_tick(xtdata, code, start_date, end_date, output_dir)

        if ok:
            success_count += 1
            total_records += count
            file_size = output_path.stat().st_size if output_path.exists() else 0
            total_size += file_size
        else:
            fail_count += 1
            errors.append((code, err))

        # 进度报告
        if i % 50 == 0 or i == total:
            elapsed = time.time() - start_time
            speed = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / speed / 60 if speed > 0 else 0
            print(f"  [{i:4d}/{total}] 成功:{success_count} 失败:{fail_count} "
                  f"记录:{total_records:,} 速度:{speed:.1f}只/s 剩余:{eta:.0f}分钟")

        # 请求间隔
        time.sleep(0.05)

    # 结果统计
    elapsed = time.time() - start_time
    print()
    print("=" * 70)
    print("下载完成")
    print(f"  总数: {total}")
    print(f"  成功: {success_count}")
    print(f"  失败: {fail_count}")
    print(f"  跳过: {skip_count}")
    print(f"  总记录: {total_records:,} 条")
    print(f"  总大小: {total_size / 1024 / 1024:.1f} MB")
    print(f"  耗时: {elapsed / 60:.1f} 分钟")
    if total > 0:
        print(f"  成功率: {(success_count + skip_count) / total * 100:.1f}%")

    # 输出前几个错误
    if errors:
        print(f"\n失败详情（前10条）：")
        for code, err in errors[:10]:
            print(f"  {code}: {err}")

    print("=" * 70)


if __name__ == "__main__":
    main()
