"""
变更日志管理系统 - 版本更新内容管理
支持版本日志创建、每日日志记录、汇总生成
"""

import os
import json
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path


class ChangelogManager:
    """变更日志管理器"""
    
    def __init__(self):
        self.root_dir = "data/logs"
        self.version_dir = os.path.join(self.root_dir, "versions")
        self.daily_dir = os.path.join(self.root_dir, "daily")
        
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        """创建必要的目录"""
        for d in [self.root_dir, self.version_dir, self.daily_dir]:
            os.makedirs(d, exist_ok=True)
    
    def create_version_changelog(self, version: str, entries: Dict[str, List[str]]):
        """
        创建版本日志
        
        参数:
            version: 版本号 (如 "V12.0")
            entries: 日志条目
                {
                    "features": ["新功能1", "新功能2"],
                    "bugfix": ["修复1"],
                    "improvements": ["改进1"],
                    "breaking": ["破坏性改动1"]
                }
        """
        version_path = os.path.join(self.version_dir, version)
        os.makedirs(version_path, exist_ok=True)
        
        # 创建各个文件
        files = {
            "FEATURES.md": self._format_md_list("新增功能", entries.get("features", [])),
            "BUGFIX.md": self._format_md_list("Bug修复", entries.get("bugfix", [])),
            "IMPROVEMENTS.md": self._format_md_list("改进", entries.get("improvements", [])),
            "BREAKING.md": self._format_md_list("破坏性改动", entries.get("breaking", []))
        }
        
        for filename, content in files.items():
            filepath = os.path.join(version_path, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
    
    def add_daily_log(self, date: str, category: str, entries: List[str]):
        """
        添加日志条目到每日日志
        
        参数:
            date: 日期 (如 "2026-02-01")
            category: 分类 (feature/bugfix/deploy/other)
            entries: 条目列表
        """
        filename = f"{date}.md"
        filepath = os.path.join(self.daily_dir, filename)
        
        content = ""
        
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        else:
            content = f"# {date} 日志\n\n"
        
        category_map = {
            "feature": "✨ 新功能",
            "bugfix": "🐛 Bug修复",
            "deploy": "🚀 部署",
            "other": "📝 其他"
        }
        
        section_title = category_map.get(category, category)
        section = f"\n## {section_title}\n"
        for entry in entries:
            section += f"- {entry}\n"
        
        content += section
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def _format_md_list(self, title: str, items: List[str]) -> str:
        """格式化Markdown列表"""
        content = f"# {title}\n\n生成时间: {datetime.now().isoformat()}\n\n"
        if not items:
            content += "_暂无内容_\n"
        else:
            for item in items:
                content += f"- {item}\n"
        return content
    
    def generate_overall_changelog(self) -> str:
        """
        生成总日志 (CHANGELOG.md)
        返回生成的内容
        """
        changelog_path = os.path.join(self.root_dir, "CHANGELOG.md")
        
        content = "# 股票量化交易系统 - 变更日志\n\n"
        content += f"*最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n"
        content += "本文档记录项目的所有重要更新和变更。\n\n"
        
        # 列出所有版本
        if os.path.exists(self.version_dir):
            versions = sorted(
                os.listdir(self.version_dir),
                key=lambda x: x.replace("V", "").replace(".", ""),
                reverse=True
            )
            
            for version in versions:
                version_path = os.path.join(self.version_dir, version)
                content += f"\n## [{version}](./{self.version_dir}/{version}/)\n\n"
                
                # 列出该版本的所有文件
                for filename in ["FEATURES.md", "BUGFIX.md", "IMPROVEMENTS.md"]:
                    filepath = os.path.join(version_path, filename)
                    if os.path.exists(filepath):
                        with open(filepath, 'r', encoding='utf-8') as f:
                            file_content = f.read()
                        # 只提取条目，不要重复标题
                        lines = file_content.split('\n')[3:]  # 跳过标题和元数据
                        for line in lines:
                            if line.strip():
                                content += f"{line}\n"
        
        with open(changelog_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return changelog_path
    
    def list_versions(self) -> List[str]:
        """列出所有版本"""
        if not os.path.exists(self.version_dir):
            return []
        
        return sorted(
            os.listdir(self.version_dir),
            key=lambda x: x.replace("V", "").replace(".", ""),
            reverse=True
        )
    
    def list_daily_logs(self, limit: int = 30) -> List[str]:
        """列出最近的每日日志"""
        if not os.path.exists(self.daily_dir):
            return []
        
        logs = sorted(
            [f[:-3] for f in os.listdir(self.daily_dir) if f.endswith('.md')],
            reverse=True
        )
        
        return logs[:limit]


# 全局实例
_manager = None


def get_changelog_manager() -> ChangelogManager:
    """获取全局变更日志管理器实例"""
    global _manager
    if _manager is None:
        _manager = ChangelogManager()
    return _manager


def init_v12_0_changelog():
    """初始化V12.0版本日志"""
    manager = get_changelog_manager()
    
    v12_0_entries = {
        "features": [
            "🎯 添加 !strategies 命令 - 显示所有可用策略的性能指标",
            "🤖 实现众包模型训练平台 - 用户可通过 !train 提交参数优化任务",
            "📊 策略注册表系统 - 维护所有策略的元数据和性能追踪",
            "⏳ 异步训练队列 - 支持并发训练、进度追踪、结果查询",
            "📝 变更日志系统 - 版本管理和每日日志记录"
        ],
        "improvements": [
            "优化 Discord 命令响应速度 - 现支持后台异步处理",
            "增强策略信息展示 - 添加更多性能指标维度",
            "改进训练结果展示 - Top N 结果聚合和排名"
        ],
        "bugfix": [
            "修复参数网格搜索中的浮点数精度问题",
            "改进数据获取的错误处理和重试机制"
        ],
        "breaking": []
    }
    
    manager.create_version_changelog("V12.0", v12_0_entries)
