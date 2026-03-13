"""
关键字预警服务
用于实时匹配转写文本中的关键字并触发预警 
"""
import re
from typing import List, Callable, Optional, Dict
from datetime import datetime
from app.core.logging import logger


class KeywordAlertService:
    """关键字预警服务类"""
    
    def __init__(self):
        """初始化关键字预警服务"""
        self.keywords: List[str] = []
        self.regex_patterns: List[re.Pattern] = []
        self.alert_history: List[Dict] = []
        self.on_alert_callback: Optional[Callable] = None
        self.max_history = 100  # 最多保存 100 条预警记录
        
    def set_keywords(self, keywords: List[str]):
        """
        设置预警关键字列表
        
        Args:
            keywords: 关键字列表
        """
        self.keywords = [k.strip() for k in keywords if k.strip()]
        self._compile_patterns()
        logger.info(f"已设置 {len(self.keywords)} 个预警关键字：{self.keywords}")
    
    def add_keyword(self, keyword: str):
        """
        添加单个关键字
        
        Args:
            keyword: 关键字
        """
        keyword = keyword.strip()
        if keyword and keyword not in self.keywords:
            self.keywords.append(keyword)
            self._compile_patterns()
            logger.info(f"添加预警关键字：{keyword}")
    
    def remove_keyword(self, keyword: str):
        """
        移除关键字
        
        Args:
            keyword: 关键字
        """
        if keyword in self.keywords:
            self.keywords.remove(keyword)
            self._compile_patterns()
            logger.info(f"移除预警关键字：{keyword}")
    
    def clear_keywords(self):
        """清空所有关键字"""
        self.keywords = []
        self.regex_patterns = []
        logger.info("已清空所有预警关键字")
    
    def _compile_patterns(self):
        """编译关键字为正则表达式模式"""
        self.regex_patterns = []
        for keyword in self.keywords:
            try:
                # 转义特殊字符，创建不区分大小写的模式
                pattern = re.compile(re.escape(keyword), re.IGNORECASE)
                self.regex_patterns.append(pattern)
            except Exception as e:
                logger.error(f"编译关键字模式失败 '{keyword}': {e}")
    
    def set_alert_callback(self, callback: Callable):
        """
        设置预警回调函数
        
        Args:
            callback: 回调函数，签名应为 (keyword: str, text: str, timestamp: str) -> None
        """
        self.on_alert_callback = callback
        logger.info("已设置预警回调函数")
    
    def check_text(self, text: str) -> List[str]:
        """
        检查文本是否包含预警关键字
        
        Args:
            text: 要检查的文本
            
        Returns:
            匹配的关键字列表
        """
        if not text or not self.regex_patterns:
            return []
        
        matched_keywords = []
        text_lower = text.lower()
        
        for i, pattern in enumerate(self.regex_patterns):
            if pattern.search(text):
                keyword = self.keywords[i]
                if keyword not in matched_keywords:
                    matched_keywords.append(keyword)
        
        return matched_keywords
    
    def process_transcription(self, text: str, timestamp: Optional[str] = None) -> List[Dict]:
        """
        处理转写文本，检查关键字并触发预警
        
        Args:
            text: 转写文本
            timestamp: 时间戳（可选）
            
        Returns:
            预警记录列表
        """
        if not text:
            return []
        
        matched = self.check_text(text)
        if not matched:
            return []
        
        # 创建预警记录
        now = datetime.now()
        alert_record = {
            "timestamp": timestamp or now.strftime("%H:%M:%S"),
            "datetime": now.isoformat(),
            "text": text,
            "matched_keywords": matched,
            "keyword_count": len(matched)
        }
        
        # 保存到历史记录
        self.alert_history.append(alert_record)
        if len(self.alert_history) > self.max_history:
            self.alert_history = self.alert_history[-self.max_history:]
        
        # 触发回调
        if self.on_alert_callback:
            try:
                self.on_alert_callback(alert_record)
            except Exception as e:
                logger.error(f"执行预警回调失败：{e}")
        
        # 记录日志
        logger.warning(f"🚨 关键字预警：{matched} | 文本：{text}")
        
        return [alert_record]
    
    def get_alert_history(self, limit: int = 10) -> List[Dict]:
        """
        获取预警历史记录
        
        Args:
            limit: 返回数量限制
            
        Returns:
            预警记录列表
        """
        return self.alert_history[-limit:]
    
    def clear_history(self):
        """清空预警历史记录"""
        self.alert_history = []
        logger.info("已清空预警历史记录")
    
    def export_alerts(self, file_path: str) -> str:
        """
        导出预警记录到文件
        
        Args:
            file_path: 输出文件路径
            
        Returns:
            文件路径
        """
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("# 关键字预警记录\n\n")
                for alert in self.alert_history:
                    f.write(f"[{alert['timestamp']}] 关键字：{', '.join(alert['matched_keywords'])}\n")
                    f.write(f"  原文：{alert['text']}\n\n")
            logger.info(f"预警记录已导出到：{file_path}")
            return file_path
        except Exception as e:
            logger.error(f"导出预警记录失败：{e}")
            raise


# 创建全局关键字预警服务实例
keyword_alert_service = KeywordAlertService()
