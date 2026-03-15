"""Allow running as: python -m data_collector"""
from .collector import main
import asyncio

asyncio.run(main())
