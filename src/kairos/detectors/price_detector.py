"""
Simple price detector for receiving price updates from exchanges.
"""

import logging
from typing import Callable, Optional

from kairos.detectors.base import BaseDetector

logger = logging.getLogger("kairos.price_detector")

class PriceDetector(BaseDetector):
    """Simple detector that receives price updates and forwards them."""
    
    def __init__(self, name: str = "price_detector"):
        super().__init__(name)
        self.callbacks = []
    
    def add_callback(self, callback: Callable):
        """Add callback for price updates."""
        self.callbacks.append(callback)
    
    def on_price_update(self, symbol: str, price: float, timestamp: float) -> None:
        """Called when a price update is received."""
        logger.debug(f"Price update: {symbol} = {price}")
        
        # 通知所有回调
        for callback in self.callbacks:
            try:
                callback(symbol, price)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    def on_volume_update(self, symbol: str, cumulative_volume: float, timestamp: float) -> None:
        """Called when a volume update is received."""
        # 忽略成交量更新
        pass