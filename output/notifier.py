"""
通知推送模块

支持：飞书机器人、企业微信机器人、控制台输出

【使用方式】
1. 在 config/settings.yaml 中设置 webhook_url
2. 或者通过环境变量 WEBHOOK_URL 设置
"""

import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Notifier:
    """
    通知推送
    
    支持多种通知渠道，默认使用控制台输出。
    配置 webhook_url 后自动切换为飞书/企业微信推送。
    """
    
    def __init__(self, webhook_url: Optional[str] = None, platform: str = "auto"):
        """
        Args:
            webhook_url: 机器人webhook地址
            platform: "feishu" / "wecom" / "console" / "auto"
        """
        self.webhook_url = webhook_url
        self.platform = platform
        
        if platform == "auto" and webhook_url:
            if "feishu" in webhook_url:
                self.platform = "feishu"
            elif "qyapi" in webhook_url:
                self.platform = "wecom"
            else:
                self.platform = "feishu"  # 默认飞书格式
    
    def send(self, title: str, content: str, msg_type: str = "text"):
        """
        发送通知
        
        Args:
            title: 通知标题
            content: 通知内容（支持Markdown）
            msg_type: text / markdown
        """
        if not self.webhook_url or self.platform == "console":
            # 控制台输出
            print(f"\n{'='*50}")
            print(f"  {title}")
            print(f"{'='*50}")
            print(content)
            return True
        
        try:
            if self.platform == "feishu":
                return self._send_feishu(title, content)
            elif self.platform == "wecom":
                return self._send_wecom(title, content)
        except Exception as e:
            logger.error(f"通知发送失败: {e}")
            return False
    
    def _send_feishu(self, title: str, content: str) -> bool:
        """飞书机器人消息"""
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "blue"
                },
                "elements": [
                    {"tag": "markdown", "content": content}
                ]
            }
        }
        resp = requests.post(self.webhook_url, json=payload, timeout=10)
        return resp.status_code == 200
    
    def _send_wecom(self, title: str, content: str) -> bool:
        """企业微信机器人消息"""
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"## {title}\n\n{content}"
            }
        }
        resp = requests.post(self.webhook_url, json=payload, timeout=10)
        return resp.status_code == 200
    
    def send_signal_report(self, report):
        """发送调仓信号报告"""
        from .reporter import DailyReport
        if isinstance(report, DailyReport):
            self.send(
                f"【{report.strategy_name}】调仓信号 {report.report_date}",
                report.to_markdown()
            )
    
    def send_alert(self, message: str):
        """发送告警"""
        self.send("⚠️ 系统告警", message)
