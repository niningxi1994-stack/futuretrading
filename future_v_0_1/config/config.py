"""
系统配置类
支持从 YAML 文件加载配置
"""

import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass
class OptionMonitorConfig:
    """期权监控器配置"""
    watch_dir: str
    persistant_dir: str


@dataclass
class ReconciliationConfig:
    """对账配置"""
    time: str  # 对账时间，格式：HH:MM:SS
    auto_fix: bool  # 是否自动修复差异


@dataclass
class SystemConfigData:
    """系统配置"""
    check_interval: int
    reconciliation: ReconciliationConfig


@dataclass
class LoggingConfig:
    """日志配置"""
    level: str
    log_file: str


class SystemConfig:
    """系统配置管理类"""
    
    def __init__(self, config_path: str):
        """
        从 YAML 文件加载配置
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self._load_config()
    
    def _load_config(self):
        """加载配置文件"""
        config_file = Path(self.config_path)
        
        if not config_file.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        
        with open(config_file, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
        
        # 保存原始配置字典（供策略等组件使用）
        self.raw_config = config_data
        
        # 解析配置
        self.option_monitor = OptionMonitorConfig(
            watch_dir=config_data['option_monitor']['watch_dir'],
            persistant_dir=config_data['option_monitor']['persistant_dir']
        )
        
        reconciliation_cfg = config_data.get('system', {}).get('reconciliation', {})
        self.system = SystemConfigData(
            check_interval=config_data['system']['check_interval'],
            reconciliation=ReconciliationConfig(
                time=reconciliation_cfg.get('time', '17:00:00'),
                auto_fix=reconciliation_cfg.get('auto_fix', True)
            )
        )
        
        self.logging = LoggingConfig(
            level=config_data.get('logging', {}).get('level', 'INFO'),
            log_file=config_data.get('logging', {}).get('log_file', 'logs/system.log')
        )
    
    def reload(self):
        """重新加载配置"""
        self._load_config()
    
    def __repr__(self):
        return (
            f"SystemConfig(\n"
            f"  option_monitor={self.option_monitor},\n"
            f"  system={self.system},\n"
            f"  logging={self.logging}\n"
            f")"
        )


if __name__ == '__main__':
    import sys
    import os
    
    # 确定配置文件路径（环境变量 > 默认路径）
    if os.environ.get('TRADING_CONFIG_PATH'):
        config_path = os.environ['TRADING_CONFIG_PATH']
    else:
        config_path = str(Path(__file__).parent.parent.parent / 'config.yaml')
    
    # 测试配置加载
    print(f"加载配置文件: {config_path}")
    try:
        config = SystemConfig(config_path)
        print(config)
        print("\n原始配置字典键:")
        print(f"  {list(config.raw_config.keys())}")
    except FileNotFoundError as e:
        print(f"❌ {e}")
        print(f"可通过环境变量指定: export TRADING_CONFIG_PATH=/path/to/config.yaml")
        sys.exit(1)

