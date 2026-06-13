import os
import logging
import json
from typing import Dict, Any

# 初始化日志器
logger = logging.getLogger(__name__)


class DeepSeekClient:
    """
    DeepSeek API 客户端封装
    负责读取环境变量并提供统一的调用接口
    """

    def __init__(self):
        # ✅ 在这里读取环境变量
        self.api_key = os.environ.get("DEEPSEEK_API_KEY")

        if not self.api_key:
            logger.error("❌ 未找到 DEEPSEEK_API_KEY 环境变量！")
            raise ValueError("请设置环境变量 DEEPSEEK_API_KEY")

        # 这里可以配置其他参数，如 base_url, model_name 等
        self.base_url = "https://api.deepseek.com/anthropic"
        self.model = "deepseek-v4-pro"

    def analyze_failure(self, request_data: Dict[str, Any], response_data: Dict[str, Any]):
        """
        示例方法：用于分析测试失败原因
        """
        logger.info(f"🧠 AI 客户端已初始化，准备分析失败用例...")
        logger.info(f"🔍 请求报文: {json.dumps(request_data, ensure_ascii=False)}")
        # 这里写具体的 AI 调用逻辑...