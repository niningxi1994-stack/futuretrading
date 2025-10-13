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
    from .utils import parse_unusualwhales_page
except ImportError:
    from utils import parse_unusualwhales_page

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

@dataclass(frozen=True)
class OptionData:
    """期权交易数据（不可变）"""
    time: datetime.datetime
    symbol: str
    side: str
    # strike: float
    option_type: str
    contract: str
    # stock_price: float
    # bid: float
    # ask: float
    # spot: float
    # size: float
    premium: float
    # volume: float



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
        self.files = [val for val in _files if val.endswith("txt")]
        self.logger.info(f"找到 {len(self.files)} 个待处理文件")

    def monitor_one_round(self):
        new_option_trade = []
        current_files = sorted(
            [str(f) for f in Path(self.watch_dir).rglob('*.txt') if f.is_file()],
            key=os.path.getctime
        )
                
                # 找出新增的文件（未处理的）
        new_files = [f for f in current_files if f not in self.processed_files]
                
        if new_files:
            self.logger.info(f"发现 {len(new_files)} 个新文件")
                    
        for file in new_files:
            # 解析文件
            records = parse_unusualwhales_page(file)
            
            # 记录原始数量
            original_count = len(self.option_tradings)
            
            # 处理每条记录
            for record in records:
                option_data = OptionData(
                    time=record['time'],
                    symbol=record['ticker'],
                    side=record['side'],
                    # strike=record['strike'],
                    option_type=record['option_type'],
                    contract=record['contract'],
                    # stock_price=record['stock_price'],
                    # bid=record['bid'],
                    # ask=record['ask'],
                    # spot=record['spot'],
                    # size=record['size'],
                    premium=record['premium'],
                    # volume=record['volume']
                )
                
                # 判断是否为新增数据
                if option_data not in self.option_tradings:
                    new_option_trade.append(option_data)
                    self.option_tradings.add(option_data)

                    self.logger.debug(
                        f"新增: {option_data.symbol} {option_data.option_type} "
                        f"${option_data.strike} 权利金=${option_data.premium:,.0f}"
                    )
            
            # 统计新增数量
            new_count = len(self.option_tradings) - original_count
            
            # 标记文件为已处理
            self.processed_files.add(file)
            
            # 保存到数据库（如果有数据库实例）
            if self.db:
                try:
                    self.db.save_processed_file(
                        file_path=file,
                        records_count=len(records),
                        new_signals_count=new_count
                    )
                except Exception as e:
                    self.logger.warning(f"保存文件处理记录失败: {e}")
            
            if new_count > 0:
                self.logger.debug(
                    f"文件: {os.path.basename(file)}, 新增 {new_count} 条"
                )
        return new_option_trade
                            

    def parse_history_data(self):
        """
        解析历史数据文件（只处理未处理过的文件）
        """
        # 过滤出未处理的文件
        unprocessed_files = [f for f in self.files if f not in self.processed_files]
        
        if not unprocessed_files:
            self.logger.info(f"历史文件已全部处理: {len(self.processed_files)}/{len(self.files)}")
            return
        
        self.logger.info(f"开始解析历史数据: {len(unprocessed_files)}/{len(self.files)} 个未处理文件")

        for idx in tqdm(range(len(unprocessed_files)), desc="解析进度"):
            file = unprocessed_files[idx]
            records = parse_unusualwhales_page(file)
            
            # 统计新增数量
            original_count = len(self.option_tradings)
            
            # 创建 OptionData 对象
            for record in records:
                option_data = OptionData(
                    time=record['time'],
                    symbol=record['ticker'],
                    side=record['side'],
                    # strike=record['strike'],
                    option_type=record['option_type'],
                    contract=record['contract'],
                    # stock_price=record['stock_price'],
                    # bid=record['bid'],
                    # ask=record['ask'],
                    # spot=record['spot'],
                    # size=record['size'],
                    premium=record['premium'],
                    # volume=record['volume']
                )
                self.option_tradings.add(option_data)
            
            # 标记为已处理
            self.processed_files.add(file)
            
            # 保存到数据库（如果有数据库实例）
            new_count = len(self.option_tradings) - original_count
            if self.db:
                try:
                    self.db.save_processed_file(
                        file_path=file,
                        records_count=len(records),
                        new_signals_count=new_count
                    )
                except Exception as e:
                    self.logger.warning(f"保存文件处理记录失败: {e}")
        
        self.logger.info(
            f"历史数据解析完成: 新增{len(unprocessed_files)}个文件, "
            f"总记录{len(self.option_tradings)}条"
        )            

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
