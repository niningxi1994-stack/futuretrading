"""
期权数据解析器
用于监控目录中的新文件并解析期权数据
"""

import datetime
import os
import time
import logging
from pathlib import Path
from dataclasses import dataclass
from tqdm import tqdm

# 处理导入（支持相对导入和直接运行）
try:
    from .utils import parse_unusualwhales_page, parse_option_csv
except ImportError:
    from utils import parse_unusualwhales_page, parse_option_csv

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

from dataclasses import dataclass, field

@dataclass(frozen=True)
class OptionData:
    """期权交易数据（不可变）"""
    time: datetime.datetime
    symbol: str
    side: str
    # strike: float
    option_type: str
    contract: str
    stock_price: float  # 恢复此字段用于备用价格方案
    # bid: float
    # ask: float
    # spot: float
    # size: float
    premium: float
    # volume: float
    metadata: dict = field(default_factory=dict, hash=False, compare=False)  # 元数据，不参与哈希和比较



class OptionMonitor:
    """期权数据监控器"""
    
    def __init__(self, watch_dir: str, persistant_dir: str, db=None):
        """
        初始化解析器
        
        Args:
            watch_dir: 监控目录路径（存放待解析的期权数据文件）
            persistant_dir: 持久化目录路径（存放处理记录和解析结果）
            db: 数据库管理器实例（可选）
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.watch_dir = watch_dir
        self.persistant_dir = persistant_dir
        self.db = db  # 数据库管理器
        self.option_tradings = set()
        self.processed_files = set()
        self.persistant_data = {"processed_files": self.processed_files, "option_tradings": self.option_tradings}        
        self._check_dir()
        
        # 注意：不在初始化时自动处理历史文件
        # 需要先从数据库恢复 processed_files，然后手动调用 parse_history_data()
        # self.parse_history_data()  # 已移除自动调用
        

    def parse(self):
        pass

    def run(self):
        pass
    
    def _check_dir(self):
        if not os.path.exists(self.watch_dir):
            raise FileNotFoundError(f"监控目录不存在: {self.watch_dir}")
        
        if not os.path.exists(self.persistant_dir):
            os.makedirs(self.persistant_dir)
            self.logger.info(f"已创建持久化目录: {self.persistant_dir}")

        _files = sorted([str(f) for f in Path(self.watch_dir).rglob('*') if f.is_file()], key=os.path.getctime)
        self.files = [val for val in _files if val.endswith("txt") or val.endswith("csv")]
        self.logger.info(f"找到 {len(self.files)} 个待处理文件")

    def monitor_one_round(self):
        new_option_trade = []
        current_files = sorted(
            [str(f) for f in Path(self.watch_dir).rglob('*') if f.is_file() and (f.suffix == '.txt' or f.suffix == '.csv')],
            key=os.path.getctime
        )
                
        # 找出新增的文件（未处理的）
        new_files = [f for f in current_files if f not in self.processed_files]
                
        if new_files:
            self.logger.info(f"发现 {len(new_files)} 个新文件")
                    
        for file in new_files:
            # 记录新文件信息
            file_name = os.path.basename(file)
            self.logger.info(f"处理新文件: {file_name}")
            
            # 判断文件格式并解析
            if file.endswith('.csv'):
                # CSV 格式处理
                result = parse_option_csv(file)
                if not result:
                    self.logger.warning(f"  文件为空或解析失败，跳过")
                    self.processed_files.add(file)
                    continue
                
                option_data = result['primary']
                history_count = len(result['historical'])
                self.logger.info(f"  CSV 格式：解析出 1 条主数据 + {history_count} 条历史数据")
                
            else:
                # TXT 格式处理（原有逻辑）
                records = parse_unusualwhales_page(file)
                self.logger.info(f"  TXT 格式：解析出 {len(records)} 条期权记录")
                
                if len(records) == 0:
                    self.logger.warning(f"  文件为空，跳过")
                    self.processed_files.add(file)
                    continue
                
                # 第1条记录作为主数据
                first_record = records[0]
                
                # 第2+条记录作为历史数据
                history_data = []
                if len(records) > 1:
                    for record in records[1:]:
                        history_data.append({
                            'time': record['time'].isoformat(),
                            'symbol': record['ticker'],
                            'side': record['side'],
                            'option_type': record['option_type'],
                            'contract': record['contract'],
                            'stock_price': record['stock_price'],
                            'premium': record['premium']
                        })
                
                # 创建 OptionData（一个文件一个对象）
                option_data = OptionData(
                    time=first_record['time'],
                    symbol=first_record['ticker'],
                    side=first_record['side'],
                    option_type=first_record['option_type'],
                    contract=first_record['contract'],
                    stock_price=first_record['stock_price'],
                    premium=first_record['premium'],
                    metadata={
                        'history_option_data': history_data,  # 历史数据列表
                        'total_records': len(records)         # 总记录数
                    }
                )
                history_count = len(history_data)
            
            # 去重判断
            if option_data not in self.option_tradings:
                new_option_trade.append(option_data)
                self.option_tradings.add(option_data)
                
                self.logger.info(
                    f"  新增期权信号: {option_data.symbol} {option_data.option_type}/{option_data.side} "
                    f"权利金=${option_data.premium:,.0f} 股价=${option_data.stock_price:.2f}"
                )
                
                if history_count > 0:
                    self.logger.info(f"  包含历史数据: {history_count} 条")
                
                new_count = 1
            else:
                self.logger.info(f"  重复信号，跳过")
                new_count = 0
            
            # 标记文件为已处理
            self.processed_files.add(file)
            
            # 保存到数据库（如果有数据库实例）
            if self.db:
                try:
                    records_count = 1 + history_count if file.endswith('.csv') else len(records)
                    self.db.save_processed_file(
                        file_path=file,
                        records_count=records_count,
                        new_signals_count=new_count
                    )
                except Exception as e:
                    self.logger.warning(f"保存文件处理记录失败: {e}")
            
            # 总结日志
            self.logger.info(
                f"  文件处理完成: 新增信号{new_count}个 (含{history_count}条历史数据)"
            )
        return new_option_trade
                            
    def parse_history_data(self):
        """
        解析历史数据文件（只处理未处理过的文件）
        
        Returns:
            List[OptionData]: 所有解析出的期权数据（包括重复的）
        """
        all_option_data = []  # 存储所有解析出的期权数据
        
        # 过滤出未处理的文件
        unprocessed_files = [f for f in self.files if f not in self.processed_files]
        
        if not unprocessed_files:
            self.logger.info(f"历史文件已全部处理: {len(self.processed_files)}/{len(self.files)}")
            return all_option_data
        
        self.logger.info(f"开始解析历史数据: {len(unprocessed_files)}/{len(self.files)} 个未处理文件")

        for idx in tqdm(range(len(unprocessed_files)), desc="解析进度"):
            file = unprocessed_files[idx]
            
            # 根据文件格式选择解析器
            if file.endswith('.csv'):
                # CSV 格式处理
                result = parse_option_csv(file)
                if not result:
                    self.processed_files.add(file)
                    continue
                
                option_data = result['primary']
                history_count = len(result['historical'])
                
            else:
                # TXT 格式处理
                records = parse_unusualwhales_page(file)
                
                if len(records) == 0:
                    self.processed_files.add(file)
                    continue
                
                # 第1条记录作为主数据
                first_record = records[0]
                
                # 第2+条记录作为历史数据
                history_data = []
                if len(records) > 1:
                    for record in records[1:]:
                        history_data.append({
                            'time': record['time'].isoformat(),
                            'symbol': record['ticker'],
                            'side': record['side'],
                            'option_type': record['option_type'],
                            'contract': record['contract'],
                            'stock_price': record['stock_price'],
                            'premium': record['premium']
                        })
                
                # 创建 OptionData（一个文件一个对象）
                option_data = OptionData(
                    time=first_record['time'],
                    symbol=first_record['ticker'],
                    side=first_record['side'],
                    option_type=first_record['option_type'],
                    contract=first_record['contract'],
                    stock_price=first_record['stock_price'],
                    premium=first_record['premium'],
                    metadata={
                        'history_option_data': history_data,
                        'total_records': len(records)
                    }
                )
                history_count = len(history_data)
            
            # 判断是否为新数据（用于去重统计）
            new_count = 0
            if option_data not in self.option_tradings:
                self.option_tradings.add(option_data)
                new_count = 1
                all_option_data.append(option_data)
            
            # 标记文件为已处理
            self.processed_files.add(file)
            
            # 保存到数据库
            if self.db:
                try:
                    records_count = 1 + history_count if file.endswith('.csv') else len(records)
                    self.db.save_processed_file(
                        file_path=file,
                        records_count=records_count,
                        new_signals_count=new_count
                    )
                except Exception as e:
                    pass
        
        return all_option_data

if __name__ == '__main__':
    from datetime import datetime
    from zoneinfo import ZoneInfo

    def get_et_datetime(date_str: str, time_str: str) -> datetime:
        """
        根据日期和时间字符串生成美东时间
        
        Args:
            date_str: 日期字符串，格式 'YYYY-MM-DD'
            time_str: 时间字符串，格式 'HH:MM'
        
        Returns:
            datetime: 带美东时区的 datetime 对象
        """
        dt_str = f"{date_str} {time_str}"
        dt_naive = datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
        return dt_naive.replace(tzinfo=ZoneInfo('America/New_York'))

    # 使用
    et_time = get_et_datetime('2025-10-10', '9:30')
    parser = OptionMonitor(
        watch_dir='/Users/niningxi/Documents/WebText/',
        persistant_dir='/Users/niningxi/Desktop/future/op_trade_data'
    )
    new_option = parser.monitor_one_round()
    print(new_option)
    # import pandas as pd
    # from dataclasses import asdict
    # # parser.parse_history_data()

    # test = parser.option_tradings
    # test = list(test)
    # a = [val for val in test if val.time > et_time]
    # a.sort(key=lambda x: x.time)

    # df = pd.DataFrame([asdict(val) for val in a])
    # print(df)
    #for val in a:
    #    print(val)
    #print(len(a))
    # print(len(test))
    # parser.monitor()
