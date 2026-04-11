from __future__ import annotations

import asyncio

from scoped_control.app import ScopedControlApp
from scoped_control.config.loader import bootstrap_repo


def test_app_launches_without_crashing(tmp_path):
    bootstrap_repo(tmp_path)

    async def run_app() -> None:
        app = ScopedControlApp(start_path=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()

    asyncio.run(run_app())
