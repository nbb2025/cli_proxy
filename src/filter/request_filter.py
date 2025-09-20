import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional


class RequestFilter:
    """请求过滤器 - 用于过滤和处理请求体数据"""
    
    def __init__(self):
        self.filter_file = Path.home() / '.clp' / 'filter.json'
        self.rules = []
    
    def load_rules(self):
        """从filter.json加载过滤规则"""
        try:
            if self.filter_file.exists():
                with open(self.filter_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                if isinstance(data, list):
                    self.rules = data
                elif isinstance(data, dict):
                    self.rules = [data]
                else:
                    self.rules = []
            else:
                self.rules = []
                
        except (json.JSONDecodeError, IOError) as e:
            print(f"加载过滤规则失败: {e}")
            self.rules = []
    
    def apply_filters(self, data: bytes) -> bytes:
        """
        对请求体数据应用过滤规则
        
        Args:
            data: 原始请求体数据(bytes)
            
        Returns:
            过滤后的请求体数据(bytes)
        """
        if not self.rules or not data:
            return data
        
        try:
            # 将bytes转换为字符串进行处理
            content = data.decode('utf-8', errors='ignore')
            
            # 应用每个过滤规则
            for rule in self.rules:
                if not isinstance(rule, dict):
                    continue
                    
                source = rule.get('source', '')
                target = rule.get('target', '')
                op = rule.get('op', 'replace')
                
                if not source:
                    continue
                
                if op == 'replace':
                    # 替换操作
                    content = content.replace(source, target)
                elif op == 'remove':
                    # 删除操作 - 用空字符串替换
                    content = content.replace(source, '')
            
            # 转换回bytes
            return content.encode('utf-8')
            
        except Exception as e:
            print(f"过滤器处理失败: {e}")
            return data
    
    def reload_rules(self):
        """重新加载过滤规则"""
        self.load_rules()

# 全局过滤器实例
request_filter = RequestFilter()

def filter_request_data(data: bytes) -> bytes:
    """
    过滤请求数据的便捷函数
    
    Args:
        data: 原始请求体数据
        
    Returns:
        过滤后的请求体数据
    """
    request_filter.load_rules()
    return request_filter.apply_filters(data)

def reload_filter_rules():
    """重新加载过滤规则的便捷函数"""
    request_filter.reload_rules()