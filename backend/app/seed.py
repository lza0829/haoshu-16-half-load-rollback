import json
from datetime import datetime, timezone

from app.db import 夹具目录, 连接

建表 = """
CREATE TABLE IF NOT EXISTS 站规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  装载日 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '装载中',
  事务号 TEXT NOT NULL DEFAULT '',
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 装载事务 (
  事务号 TEXT PRIMARY KEY,
  批号 TEXT NOT NULL UNIQUE,
  装载日 TEXT NOT NULL,
  提交时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 枢纽_号卡 (
  哈希键 TEXT PRIMARY KEY,
  业务键 TEXT NOT NULL UNIQUE,
  装载日 TEXT NOT NULL,
  批号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 枢纽_套餐 (
  哈希键 TEXT PRIMARY KEY,
  业务键 TEXT NOT NULL UNIQUE,
  装载日 TEXT NOT NULL,
  批号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 枢纽_客户 (
  哈希键 TEXT PRIMARY KEY,
  业务键 TEXT NOT NULL UNIQUE,
  装载日 TEXT NOT NULL,
  批号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 链接_号卡套餐 (
  哈希键 TEXT PRIMARY KEY,
  号卡哈希 TEXT NOT NULL REFERENCES 枢纽_号卡(哈希键),
  套餐哈希 TEXT NOT NULL REFERENCES 枢纽_套餐(哈希键),
  装载日 TEXT NOT NULL,
  批号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 链接_号卡客户 (
  哈希键 TEXT PRIMARY KEY,
  号卡哈希 TEXT NOT NULL REFERENCES 枢纽_号卡(哈希键),
  客户哈希 TEXT NOT NULL REFERENCES 枢纽_客户(哈希键),
  装载日 TEXT NOT NULL,
  批号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 卫星_号卡属性 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  号卡哈希 TEXT NOT NULL REFERENCES 枢纽_号卡(哈希键),
  装载日 TEXT NOT NULL,
  载荷哈希 TEXT NOT NULL,
  属性 TEXT NOT NULL,
  是否当前 INTEGER NOT NULL DEFAULT 1,
  批号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 卫星_套餐属性 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  套餐哈希 TEXT NOT NULL REFERENCES 枢纽_套餐(哈希键),
  装载日 TEXT NOT NULL,
  载荷哈希 TEXT NOT NULL,
  属性 TEXT NOT NULL,
  是否当前 INTEGER NOT NULL DEFAULT 1,
  批号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 卫星_客户属性 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  客户哈希 TEXT NOT NULL REFERENCES 枢纽_客户(哈希键),
  装载日 TEXT NOT NULL,
  载荷哈希 TEXT NOT NULL,
  属性 TEXT NOT NULL,
  是否当前 INTEGER NOT NULL DEFAULT 1,
  批号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 卫星_订购属性 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  链接哈希 TEXT NOT NULL REFERENCES 链接_号卡套餐(哈希键),
  装载日 TEXT NOT NULL,
  载荷哈希 TEXT NOT NULL,
  属性 TEXT NOT NULL,
  是否当前 INTEGER NOT NULL DEFAULT 1,
  批号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 隔离匣 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  原因 TEXT NOT NULL,
  载荷 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 金库贯验 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  枢纽数 INTEGER NOT NULL,
  链接数 INTEGER NOT NULL,
  卫星当前数 INTEGER NOT NULL,
  是否通过 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
"""

# 台账前已有库的补列迁移：老批次行只在成功时落账，故状态补列为「成功」；
# 老正式行批号补空串，贯验视空批号为台账前遗留、不参与半截扫描。
补列 = [
    ("装载批次", "状态", "TEXT NOT NULL DEFAULT '成功'"),
    ("装载批次", "事务号", "TEXT NOT NULL DEFAULT ''"),
] + [
    (表, "批号", "TEXT NOT NULL DEFAULT ''")
    for 表 in (
        "枢纽_号卡", "枢纽_套餐", "枢纽_客户",
        "链接_号卡套餐", "链接_号卡客户",
        "卫星_号卡属性", "卫星_套餐属性", "卫星_客户属性", "卫星_订购属性",
    )
]


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 哈希键(*parts: str) -> str:
    import hashlib

    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]


def 载荷哈希(obj) -> str:
    import hashlib

    s = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def 初始化库() -> None:
    conn = 连接()
    conn.executescript(建表)
    for 表, 列, 定义 in 补列:
        现有 = {r["name"] for r in conn.execute(f"PRAGMA table_info({表})")}
        if 列 not in 现有:
            conn.execute(f"ALTER TABLE {表} ADD COLUMN {列} {定义}")
    if conn.execute("SELECT COUNT(*) AS c FROM 站规").fetchone()["c"] == 0:
        for k, v in {"站名": "号枢", "默认装载日": "2026-11-21"}.items():
            conn.execute("INSERT INTO 站规(键, 值) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()
