import json
import logging
import queue
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import requests

from app import config

logger = logging.getLogger("course_chatbot.notifier")


class BaseNotifier(ABC):
    @abstractmethod
    def send(self, event_type: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        pass


class CallMeBotNotifier(BaseNotifier):
    URL = "https://api.callmebot.com/whatsapp.php"

    def __init__(self, phone: Optional[str] = None, apikey: Optional[str] = None):
        self.phone = phone if phone is not None else config.CALLMEBOT_PHONE
        self.apikey = apikey if apikey is not None else config.CALLMEBOT_APIKEY

    def send(self, event_type: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        if config.TEST_MODE or not self.phone or not self.apikey:
            return False
        try:
            params = {"phone": self.phone, "text": message, "apikey": self.apikey}
            res = requests.get(self.URL, params=params, timeout=8)
            if res.status_code == 200:
                logger.info(f"[CallMeBot] Successfully delivered {event_type} notification.")
                return True
            else:
                logger.warning(f"[CallMeBot] Error ({res.status_code}): {res.text}")
                return False
        except Exception as e:
            logger.warning(f"[CallMeBot] Request failed: {e}")
            return False


class WebhookNotifier(BaseNotifier):
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url if webhook_url is not None else config.CRM_WEBHOOK_URL

    def send(self, event_type: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        if config.TEST_MODE or not self.webhook_url:
            return False
        try:
            payload = {
                "event": event_type,
                "message": message,
                "metadata": metadata or {},
                "timestamp": time.time(),
            }
            res = requests.post(self.webhook_url, json=payload, timeout=6)
            if res.status_code in [200, 201, 202, 204]:
                logger.info(f"[Webhook] Successfully sent {event_type} event to CRM.")
                return True
            else:
                logger.warning(f"[Webhook] Returned non-200 status {res.status_code}")
                return False
        except Exception as e:
            logger.warning(f"[Webhook] Request failed: {e}")
            return False


class NotificationDispatcher:
    """Non-blocking notification worker with retry and multi-notifier support."""

    def __init__(self):
        self.notifiers: List[BaseNotifier] = []
        if config.CALLMEBOT_PHONE and config.CALLMEBOT_APIKEY:
            self.notifiers.append(CallMeBotNotifier())
        if config.CRM_WEBHOOK_URL:
            self.notifiers.append(WebhookNotifier())

        self.queue: queue.Queue = queue.Queue(maxsize=1000)
        self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self._worker_thread.start()

    def dispatch(
        self,
        event_type: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ):
        if config.TEST_MODE and not force:
            logger.info(f"[Notifier] Skipped '{event_type}' — TEST_MODE is active.")
            return

        if not self.notifiers:
            return

        try:
            self.queue.put_nowait((event_type, message, metadata, 0))
        except queue.Full:
            logger.error("Notification queue is full! Dropping oldest notification.")

    def _process_queue(self):
        while True:
            try:
                event_type, message, metadata, retries = self.queue.get()
                all_succeeded = True
                for n in self.notifiers:
                    try:
                        ok = n.send(event_type, message, metadata)
                        if not ok:
                            all_succeeded = False
                    except Exception as e:
                        logger.warning(f"Notifier {type(n)} failed: {e}")
                        all_succeeded = False

                if not all_succeeded and retries < 1 and not config.TEST_MODE:
                    time.sleep(1)
                    self.queue.put((event_type, message, metadata, retries + 1))

                self.queue.task_done()
            except Exception as e:
                logger.error(f"Error processing notification queue: {e}")
                time.sleep(1)


dispatcher = NotificationDispatcher()
