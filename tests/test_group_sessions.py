import types
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import Field, SQLModel

import astrbot.core.db.po as po
from core.panels_web import group_sessions


class UmoSender(SQLModel, table=True):
    """与 AstrBot v4.29.4+ 的 umo_senders 表结构一致，本地 AstrBot 版本较旧时用它代替。"""

    __tablename__ = "test_umo_senders"
    __table_args__ = (UniqueConstraint("umo", "sender_id"), {"extend_existing": True})

    id: int | None = Field(default=None, primary_key=True)
    umo: str
    sender_id: str
    sender_name: str = ""
    updated_at: datetime


class GroupSessionsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all, tables=[UmoSender.__table__])
        base = datetime(2026, 11, 1)
        rows = [
            # 同一个人先在 G1、后在 G2 说话；AstrBot 按发送者去重时 G1 会被漏掉。
            ("bot_a:GroupMessage:G1", "U1", 1),
            ("bot_a:GroupMessage:G2", "U1", 3),
            ("bot_a:GroupMessage:U2_G3", "U2", 2),
            ("bot_a:FriendMessage:U1", "U1", 4),
            ("botXa:GroupMessage:G9", "U9", 5),
        ]
        async with AsyncSession(self.engine) as session:
            for umo, sender_id, hour in rows:
                session.add(UmoSender(umo=umo, sender_id=sender_id, updated_at=base + timedelta(hours=hour)))
            await session.commit()

        engine = self.engine
        aliases = []

        @asynccontextmanager
        async def get_db():
            async with AsyncSession(engine) as session:
                yield session

        async def get_umo_aliases(umos):
            aliases.append(list(umos))
            return [types.SimpleNamespace(umo="bot_a:GroupMessage:G1", user_alias="主群", auto_name="")]

        self.aliases = aliases
        self.db = types.SimpleNamespace(get_db=get_db, get_umo_aliases=get_umo_aliases)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_lists_every_group_newest_first(self):
        with patch.object(po, "UmoSender", UmoSender, create=True):
            records = await group_sessions(self.db, "bot_a:GroupMessage:", 1000)
        umos = [sender.umo for sender, _ in records]
        # 机器人 ID 里的下划线按字面匹配，不会把 botXa 也算进来。
        self.assertEqual(umos, ["bot_a:GroupMessage:G2", "bot_a:GroupMessage:U2_G3", "bot_a:GroupMessage:G1"])
        self.assertEqual(records[2][1].user_alias, "主群")
        self.assertIsNone(records[0][1])
        self.assertEqual(self.aliases, [umos])

    async def test_limit(self):
        with patch.object(po, "UmoSender", UmoSender, create=True):
            records = await group_sessions(self.db, "bot_a:GroupMessage:", 1)
        self.assertEqual([sender.umo for sender, _ in records], ["bot_a:GroupMessage:G2"])
