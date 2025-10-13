"""
期权数据解析工具模块
用于解析 UnusualWhales 期权流数据文件
"""

import pandas as pd
import re
import os
from datetime import datetime
from typing import Optional, List, Dict
from zoneinfo import ZoneInfo

def parse_et_time(time_str: str) -> datetime:
    """
    解析包含 EDT/EST 时区的时间字符串
    例如: '2025-10-06 14:01:19 EDT'
    """
    # 移除时区标识（EDT/EST）
    dt_str = time_str.rsplit(' ', 1)[0]
    
    # 解析为 naive datetime
    dt_naive = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
    
    # 添加美东时区
    dt_aware = dt_naive.replace(tzinfo=ZoneInfo('America/New_York'))
    
    return dt_aware

def _extract_date_from_filename(file_path: str) -> Optional[datetime]:
    """从文件名中提取日期，例如 page_20251007_211426.txt -> 2025-10-07"""
    basename = os.path.basename(file_path)
    # 匹配格式: page_YYYYMMDD_HHMMSS.txt
    match = re.search(r'page_(\d{8})_\d{6}', basename)
    if match:
        date_str = match.group(1)
        try:
            return datetime.strptime(date_str, '%Y%m%d')
        except:
            return None
    return None


def _convert_beijing_to_et(time_str: str, reference_date: datetime) -> str:
    """
    将北京时间（GMT+8）转换为美东时间（ET）
    
    Args:
        time_str: 北京时间字符串，格式 "MM/DD HH:MM:SS"
        reference_date: 参考日期（用于确定年份）
        
    Returns:
        美东时间字符串，格式 "YYYY-MM-DD HH:MM:SS ET"
    """
    try:
        # 解析时间字符串 "10/07 03:58:54"
        parts = time_str.split()
        date_part = parts[0]  # "10/07"
        time_part = parts[1]  # "03:58:54"
        
        month_day = date_part.split('/')
        month = int(month_day[0])
        day = int(month_day[1])
        
        time_parts = time_part.split(':')
        hour = int(time_parts[0])
        minute = int(time_parts[1])
        second = int(time_parts[2])
        
        # 使用参考日期的年份
        year = reference_date.year
        
        # 创建北京时间的 datetime 对象（带时区）
        beijing_tz = ZoneInfo('Asia/Shanghai')
        beijing_time = datetime(year, month, day, hour, minute, second, tzinfo=beijing_tz)
        
        # 转换为美东时间
        et_tz = ZoneInfo('America/New_York')
        et_time = beijing_time.astimezone(et_tz)
        
        # 格式化输出（包含时区标识）
        # 判断是 EST 还是 EDT
        tz_name = et_time.strftime('%Z')  # EST 或 EDT
        formatted_time = et_time.strftime('%Y-%m-%d %H:%M:%S') + f' {tz_name}'
        
        return formatted_time
        
    except Exception as e:
        # 转换失败，返回原始字符串
        return time_str


def parse_unusualwhales_page(file_path: str, convert_timezone: bool = True) -> pd.DataFrame:
    """
    解析 UnusualWhales 期权流数据文件 (page_YYYYMMDD_HHMMSS.txt)
    
    Args:
        file_path: 文件路径
        convert_timezone: 是否将时间从北京时间（GMT+8）转换为美东时间（ET），默认 True
        
    Returns:
        pd.DataFrame: 包含期权交易数据的DataFrame，列包括：
            - time: 交易时间（如果 convert_timezone=True，则为美东时间；否则为北京时间）
            - time_beijing: 原始北京时间（仅当 convert_timezone=True 时添加）
            - ticker: 股票代码
            - side: 方向 (ASK/BID)
            - strike: 行权价
            - option_type: 期权类型 (call/put)
            - expiration: 到期日
            - dte: 距离到期天数
            - stock_price: 股票价格
            - bid: 买价
            - ask: 卖价
            - spot: 成交价
            - size: 数量
            - premium: 权利金
            - volume: 成交量
            - open_interest: 持仓量
            - chain_bid_ask_pct: 链上买卖比例
            - legs: 腿数 (SL=single leg, ML=multi leg)
            - code: 交易代码
            - flags: 标记/标签
    """
    
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = [line.rstrip('\n') for line in f.readlines()]
    
    # 从文件名提取日期信息（用于时区转换）
    reference_date = _extract_date_from_filename(file_path)
    if reference_date is None:
        # 如果无法从文件名提取日期，使用当前年份
        reference_date = datetime.now()
    
    # 找到数据开始的位置 (表头后的第一条数据)
    data_start_idx = None
    for i, line in enumerate(lines):
        if line.startswith('Time - GMT+8'):
            # 表头行，数据从下一个非空行开始
            data_start_idx = i + 1
            break
    
    if data_start_idx is None:
        return pd.DataFrame()
    
    # 解析数据
    records = []
    i = data_start_idx
    
    while i < len(lines):
        line = lines[i].strip()
        
        # 跳过空行和特殊行
        if not line or line.startswith('Unusual Whales') or line.startswith('Powered by'):
            i += 1
            continue
        
        # 检查是否是时间行 (格式: MM/DD HH:MM:SS)
        time_match = re.match(r'^\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}$', line)
        if time_match:
            # 这是一个新记录的开始
            try:
                time_str = line
                
                # 下一行应该是股票代码
                if i + 1 >= len(lines):
                    break
                ticker = lines[i + 1].strip()
                
                # 再下一行是主数据行
                if i + 2 >= len(lines):
                    break
                data_line = lines[i + 2].strip()
                
                # 解析主数据行
                parts = data_line.split('\t')
                if len(parts) < 10:
                    # 数据不完整，跳过
                    i += 1
                    continue
                
                # 提取字段
                side = parts[0] if len(parts) > 0 else ''
                strike = parts[1] if len(parts) > 1 else ''
                option_type = parts[2] if len(parts) > 2 else ''
                expiration = parts[3] if len(parts) > 3 else ''
                dte = parts[4] if len(parts) > 4 else ''
                stock_price = parts[5] if len(parts) > 5 else ''
                bid_ask = parts[6] if len(parts) > 6 else ''
                spot = parts[7] if len(parts) > 7 else ''
                size = parts[8] if len(parts) > 8 else ''
                premium = parts[9] if len(parts) > 9 else ''
                volume = parts[10] if len(parts) > 10 else ''
                oi = parts[11] if len(parts) > 11 else ''
                
                # 解析 bid-ask 范围
                bid, ask = _parse_bid_ask(bid_ask)
                
                # 后续行包含额外信息
                chain_pct = ''
                legs = ''
                code = ''
                flags = ''
                
                if i + 3 < len(lines):
                    chain_pct = lines[i + 3].strip()
                if i + 4 < len(lines):
                    legs = lines[i + 4].strip()
                if i + 5 < len(lines):
                    code = lines[i + 5].strip()
                if i + 6 < len(lines):
                    flags = lines[i + 6].strip()
                
                # 时区转换
                if convert_timezone:
                    time_et = _convert_beijing_to_et(time_str, reference_date)
                    time_beijing = time_str
                else:
                    time_et = time_str
                    time_beijing = None
                
                # 创建记录
                record = {
                    'time': parse_et_time(time_et),
                    'ticker': ticker,
                    'side': side,
                    'strike': _parse_number(strike),
                    'option_type': option_type,
                    'contract': expiration,
                    'stock_price': _parse_currency(stock_price),
                    'bid': bid,
                    'ask': ask,
                    'spot': _parse_currency(spot),
                    'size': _parse_number(size),
                    'premium': _parse_premium(premium),
                    'volume': _parse_number(volume),
                    'open_interest': _parse_number(oi),
                    'chain_bid_ask_pct': _parse_percentage(chain_pct),
                    'legs': legs,
                    'code': code,
                    'flags': flags
                }
                
                # 添加原始北京时间（仅在转换时）
                if convert_timezone and time_beijing:
                    record['time_beijing'] = time_beijing
                
                records.append(record)
                
                # 跳过已处理的行
                i += 7  # 时间 + 代码 + 数据行 + 4行额外信息
                
            except Exception as e:
                # 解析出错，跳过这条记录
                i += 1
                continue
        else:
            i += 1
    
    return records


def _parse_bid_ask(bid_ask_str: str) -> tuple[Optional[float], Optional[float]]:
    """解析 bid-ask 字符串，例如 '$15.20 - $18.90'"""
    if not bid_ask_str or '-' not in bid_ask_str:
        return None, None
    
    try:
        parts = bid_ask_str.split('-')
        bid = _parse_currency(parts[0].strip())
        ask = _parse_currency(parts[1].strip())
        return bid, ask
    except:
        return None, None


def _parse_currency(value: str) -> Optional[float]:
    """解析货币字符串，例如 '$588.63'"""
    if not value:
        return None
    
    try:
        # 移除 $, 逗号等符号
        cleaned = value.replace('$', '').replace(',', '').strip()
        return float(cleaned)
    except:
        return None


def _parse_premium(value: str) -> Optional[float]:
    """解析权利金字符串，例如 '$264K' -> 264000"""
    if not value:
        return None
    
    try:
        cleaned = value.replace('$', '').replace(',', '').strip().upper()
        
        if cleaned.endswith('K'):
            return float(cleaned[:-1]) * 1000
        elif cleaned.endswith('M'):
            return float(cleaned[:-1]) * 1000000
        else:
            return float(cleaned)
    except:
        return None


def _parse_number(value: str) -> Optional[float]:
    """解析数字字符串"""
    if not value:
        return None
    
    try:
        cleaned = value.replace(',', '').strip()
        return float(cleaned)
    except:
        return None


def _parse_percentage(value: str) -> Optional[float]:
    """解析百分比字符串，例如 '84%' -> 84.0"""
    if not value:
        return None
    
    try:
        cleaned = value.replace('%', '').strip()
        return float(cleaned)
    except:
        return None





# 示例用法
if __name__ == '__main__':
    # 测试解析
    test_file = '/Users/niningxi/Desktop/future/demo/page_20251007_211426.txt'
    df = parse_unusualwhales_page(test_file)
    df.to_csv('./test.csv')    


