#!/usr/bin/env python3
"""
缓存请求过滤器 - 优化过滤规则加载性能
通过监控文件修改时间来决定是否重新加载
"""
import json
import re
import time
from pathlib import Path
from typing import List, Dict, Any

class CachedRequestFilter:
    """带缓存的请求过滤器"""
    
    def __init__(self, cache_check_interval: float = 1.0):
        """
        初始化缓存过滤器
        
        Args:
            cache_check_interval: 检查文件修改的最小间隔（秒）
        """
        self.filter_file = Path.home() / '.clp' / 'filter.json'
        self._rules = []
        self._file_mtime = 0
        self._last_check_time = 0
        self.cache_check_interval = cache_check_interval
    
    def _should_reload(self) -> bool:
        """
        检查是否需要重新加载规则
        通过文件修改时间判断
        """
        # 限制检查频率，避免过于频繁的stat调用
        current_time = time.time()
        if current_time - self._last_check_time < self.cache_check_interval:
            return False
        
        self._last_check_time = current_time
        
        try:
            if not self.filter_file.exists():
                # 文件不存在，如果之前有规则则清空
                if self._rules:
                    self._rules = []
                    self._file_mtime = 0
                    return True
                return False
            
            current_mtime = self.filter_file.stat().st_mtime
            if current_mtime != self._file_mtime:
                return True
            
            return False
        except (OSError, FileNotFoundError):
            return False
    
    def load_rules(self, force: bool = False):
        """
        加载过滤规则（使用缓存）
        
        Args:
            force: 是否强制重新加载
        """
        if not force and not self._should_reload():
            return  # 使用缓存的规则
        
        try:
            if not self.filter_file.exists():
                self._rules = []
                self._file_mtime = 0
                return
            
            with open(self.filter_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 验证并处理规则格式
            if isinstance(data, list):
                self._rules = data
            elif isinstance(data, dict):
                self._rules = [data]
            else:
                print(f"警告: 过滤规则格式错误，必须是对象或对象数组")
                self._rules = []
            
            # 预编译正则表达式以提高性能
            for rule in self._rules:
                if 'source' in rule and 'regex' not in rule:
                    # 如果source包含正则表达式特殊字符，编译为正则
                    try:
                        rule['regex'] = re.compile(rule['source'].encode('utf-8'), re.DOTALL)
                    except re.error:
                        # 如果编译失败，作为普通字符串处理
                        rule['regex'] = None
            
            # 更新文件修改时间
            self._file_mtime = self.filter_file.stat().st_mtime
            
            print(f"过滤规则已加载: {len(self._rules)} 条规则")
            
        except json.JSONDecodeError as e:
            print(f"过滤规则文件JSON格式错误: {e}")
            self._rules = []
        except Exception as e:
            print(f"加载过滤规则失败: {e}")
            self._rules = []
    
    def apply_filters(self, data: bytes) -> bytes:
        """
        应用过滤规则到请求数据
        
        Args:
            data: 原始请求数据
            
        Returns:
            过滤后的数据
        """
        # 确保规则已加载（使用缓存）
        self.load_rules()
        
        if not self._rules or not data:
            return data
        
        # 应用每个过滤规则
        filtered_data = data
        for rule in self._rules:
            if 'op' not in rule or 'source' not in rule:
                continue
            
            op = rule['op']
            source = rule['source'].encode('utf-8')
            
            if op == 'replace':
                target = rule.get('target', '').encode('utf-8')
                
                # 优先使用预编译的正则表达式
                if 'regex' in rule and rule['regex']:
                    filtered_data = rule['regex'].sub(target, filtered_data)
                else:
                    # 普通字符串替换
                    filtered_data = filtered_data.replace(source, target)
                    
            elif op == 'remove':
                # 删除操作
                if 'regex' in rule and rule['regex']:
                    filtered_data = rule['regex'].sub(b'', filtered_data)
                else:
                    filtered_data = filtered_data.replace(source, b'')
        
        return filtered_data
    
    def get_rules_count(self) -> int:
        """获取当前加载的规则数量"""
        self.load_rules()  # 确保规则是最新的
        return len(self._rules)
    
    def get_rules(self) -> List[Dict[str, Any]]:
        """获取当前的规则列表（只读）"""
        self.load_rules()  # 确保规则是最新的
        # 返回副本，避免外部修改
        return [rule.copy() for rule in self._rules if 'regex' not in rule]
    
    def force_reload(self):
        """强制重新加载规则"""
        self.load_rules(force=True)

# 创建全局实例
request_filter = CachedRequestFilter()

def filter_request_data(data: bytes) -> bytes:
    """
    兼容性函数 - 保持与原版本相同的接口
    
    Args:
        data: 原始请求数据
        
    Returns:
        过滤后的数据
    """
    return request_filter.apply_filters(data)