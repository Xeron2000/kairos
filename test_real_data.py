#!/usr/bin/env python3
"""Test real exchange WebSocket connection."""

import asyncio
import sys
import time
sys.path.insert(0, "src")

from kairos.data.data_manager import data_service, ExchangeType

async def test_real_data():
    """Test real exchange data."""
    print("Testing real exchange WebSocket connection...")
    
    # 初始化数据服务
    await data_service.initialize(["okx", "bybit"])
    
    # 添加回调
    def on_data_update(data):
        print(f"Data update: {data.symbol} @ {data.exchange} = {data.price}")
    
    data_service.add_callback(on_data_update)
    
    # 启动数据收集
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    print(f"Starting data collection for {symbols}...")
    
    # 启动数据收集（异步任务）
    task = asyncio.create_task(data_service.start(symbols))
    
    # 等待数据
    print("Waiting for data...")
    for i in range(10):
        await asyncio.sleep(1)
        
        # 获取价格
        btc_price = data_service.get_price("BTC/USDT")
        eth_price = data_service.get_price("ETH/USDT")
        sol_price = data_service.get_price("SOL/USDT")
        
        print(f"BTC: {btc_price}, ETH: {eth_price}, SOL: {sol_price}")
    
    # 停止数据收集
    await data_service.stop()
    task.cancel()
    
    print("Test completed!")

if __name__ == "__main__":
    asyncio.run(test_real_data())