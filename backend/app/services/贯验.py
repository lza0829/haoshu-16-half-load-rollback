"""贯验服务：贯穿互证 + 半截装载回滚核对（口径甲·单事务原子回滚）。"""
import json

from app.db import 连接
from app.seed import 此刻

口径甲 = "甲·单事务原子回滚（无段间提交、无补偿路径）"

三族表 = {
    "枢纽": ("枢纽_号卡", "枢纽_套餐", "枢纽_客户"),
    "链接": ("链接_号卡套餐", "链接_号卡客户"),
    "卫星": ("卫星_号卡属性", "卫星_套餐属性", "卫星_客户属性", "卫星_订购属性"),
}
全部正式表 = tuple(t for 表s in 三族表.values() for t in 表s)


def _批增量(conn, 批号: str) -> dict:
    增量 = {}
    for 族, 表s in 三族表.items():
        增量[族] = sum(
            conn.execute(f"SELECT COUNT(*) AS c FROM {t} WHERE 批号=?", (批号,)).fetchone()["c"]
            for t in 表s
        )
    增量["合计"] = 增量["枢纽"] + 增量["链接"] + 增量["卫星"]
    return 增量


def _查半截(conn, 批号: str) -> dict:
    """只读核对：批号、成败、三族该批增量、事务证据、一致性结论。"""
    批 = conn.execute("SELECT * FROM 装载批次 WHERE 编号=?", (批号,)).fetchone()
    增量 = _批增量(conn, 批号)
    日志 = conn.execute("SELECT * FROM 装载事务 WHERE 批号=?", (批号,)).fetchone()
    问题 = []
    if not 批:
        if 增量["合计"]:
            问题.append(f"无批次台账却有正式增量{增量['合计']}笔")
        return {
            "批号": 批号,
            "批次状态": "无记录",
            "成败": False,
            "增量": 增量,
            "证据": {"口径": 口径甲, "事务号": "", "事务日志": "无"},
            "贯验通过": not 问题,
            "问题": 问题,
        }
    状态 = 批["状态"]
    事务号 = 批["事务号"]
    日志在 = bool(日志) and 日志["事务号"] == 事务号
    备注 = None
    if 状态 == "成功":
        if 事务号:
            if not 日志在:
                问题.append("标成功却缺同事务提交证据（装载事务日志缺失或事务号不符）")
            报告 = json.loads(批["报告"] or "{}")
            for 族 in ("枢纽", "链接", "卫星"):
                报数 = 报告.get(族)
                if 报数 is not None and 报数 != 增量[族]:
                    问题.append(f"{族}该批增量{增量[族]}与批次报告{报数}不符（疑似正式已清扫而批次仍成功）")
        else:
            备注 = "台账前遗留批次，免半截核对"
    elif 状态 == "失败":
        if 增量["合计"]:
            问题.append(f"失败批残留正式增量{增量['合计']}笔（口径甲无补偿路径，残留即外带污染）")
        if 日志:
            问题.append("失败批却存在装载事务日志（提交证据与失败标志分叉）")
    elif 状态 == "装载中":
        问题.append("批次未终结（装载中悬挂），按失败闭处理")
        if 增量["合计"]:
            问题.append(f"未终结批已有正式增量{增量['合计']}笔（半截落库）")
    else:
        问题.append(f"非法批次状态:{状态}")
    出 = {
        "批号": 批号,
        "批次状态": 状态,
        "成败": 状态 == "成功",
        "增量": 增量,
        "证据": {
            "口径": 口径甲,
            "事务号": 事务号,
            "事务日志": "存在" if 日志在 else ("缺失" if 事务号 else "无（遗留批次）"),
            "日志详情": dict(日志) if 日志 else None,
        },
        "贯验通过": not 问题,
        "问题": 问题,
    }
    if 备注:
        出["备注"] = 备注
    return 出


def 查半截回滚(批号: str) -> dict:
    """只读接口：单批半截回滚核对。"""
    conn = 连接()
    try:
        return _查半截(conn, 批号)
    finally:
        conn.close()


def 扫半截回滚() -> dict:
    """只读接口：全批次扫描——零残留、同事务证据、未终结、无账增量。"""
    conn = 连接()
    try:
        明细 = [
            _查半截(conn, r["编号"])
            for r in conn.execute("SELECT 编号 FROM 装载批次 ORDER BY 时刻, 编号")
        ]
        问题 = [f"{m['批号']}:{p}" for m in 明细 for p in m["问题"]]
        台账 = {m["批号"] for m in 明细}
        无账 = set()
        for t in 全部正式表:
            for r in conn.execute(f"SELECT DISTINCT 批号 AS b FROM {t} WHERE 批号<>''"):
                if r["b"] not in 台账:
                    无账.add(r["b"])
        for b in sorted(无账):
            问题.append(f"无账增量:正式表存在批号{b}却无批次台账")
        return {
            "口径": 口径甲,
            "贯验通过": not 问题,
            "批次数": len(明细),
            "问题": 问题,
            "明细": 明细,
        }
    finally:
        conn.close()


def 跑贯验() -> dict:
    conn = 连接()
    try:
        枢纽数 = sum(
            conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
            for t in ("枢纽_号卡", "枢纽_套餐", "枢纽_客户")
        )
        链接数 = sum(
            conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
            for t in ("链接_号卡套餐", "链接_号卡客户")
        )
        卫星当前数 = sum(
            conn.execute(f"SELECT COUNT(*) AS c FROM {t} WHERE 是否当前=1").fetchone()["c"]
            for t in ("卫星_号卡属性", "卫星_套餐属性", "卫星_客户属性", "卫星_订购属性")
        )

        缺链 = []
        for r in conn.execute("SELECT * FROM 链接_号卡套餐"):
            if not conn.execute("SELECT 1 FROM 枢纽_号卡 WHERE 哈希键=?", (r["号卡哈希"],)).fetchone():
                缺链.append(f"订购链缺号卡枢纽:{r['哈希键']}")
            if not conn.execute("SELECT 1 FROM 枢纽_套餐 WHERE 哈希键=?", (r["套餐哈希"],)).fetchone():
                缺链.append(f"订购链缺套餐枢纽:{r['哈希键']}")
        for r in conn.execute("SELECT * FROM 链接_号卡客户"):
            if not conn.execute("SELECT 1 FROM 枢纽_号卡 WHERE 哈希键=?", (r["号卡哈希"],)).fetchone():
                缺链.append(f"实名链缺号卡:{r['哈希键']}")
            if not conn.execute("SELECT 1 FROM 枢纽_客户 WHERE 哈希键=?", (r["客户哈希"],)).fetchone():
                缺链.append(f"实名链缺客户:{r['哈希键']}")

        孤儿 = []
        for 表, 列, 父表 in (
            ("卫星_号卡属性", "号卡哈希", "枢纽_号卡"),
            ("卫星_套餐属性", "套餐哈希", "枢纽_套餐"),
            ("卫星_客户属性", "客户哈希", "枢纽_客户"),
            ("卫星_订购属性", "链接哈希", "链接_号卡套餐"),
        ):
            for r in conn.execute(f"SELECT {列} AS p FROM {表} WHERE 是否当前=1"):
                if not conn.execute(f"SELECT 1 FROM {父表} WHERE 哈希键=?", (r["p"],)).fetchone():
                    孤儿.append(f"{表}:{r['p']}")

        双当前 = []
        for 表, 列 in (
            ("卫星_号卡属性", "号卡哈希"),
            ("卫星_套餐属性", "套餐哈希"),
            ("卫星_客户属性", "客户哈希"),
            ("卫星_订购属性", "链接哈希"),
        ):
            for r in conn.execute(
                f"SELECT {列} AS p, COUNT(*) AS c FROM {表} WHERE 是否当前=1 GROUP BY {列} HAVING c>1"
            ):
                双当前.append(f"{表}:{r['p']}")

        半截 = 扫半截回滚()

        检项 = [
            {
                "名": "链接两端可解",
                "通过": len(缺链) == 0,
                "说明": "全部链接两端枢纽可解" if not 缺链 else "；".join(缺链[:6]),
            },
            {
                "名": "卫星无孤儿",
                "通过": len(孤儿) == 0,
                "说明": "当前卫星均挂到合法父键" if not 孤儿 else "；".join(孤儿[:6]),
            },
            {
                "名": "无双当前",
                "通过": len(双当前) == 0,
                "说明": "同父键仅一条当前卫星" if not 双当前 else "；".join(双当前[:6]),
            },
            {
                "名": "半截回滚零残留",
                "通过": 半截["贯验通过"],
                "说明": (
                    "失败批零增量、成功批有同事务证据、无未终结批、无无账增量"
                    if 半截["贯验通过"]
                    else "；".join(半截["问题"][:6])
                ),
            },
        ]
        问题 = 缺链 + [f"孤儿卫星:{x}" for x in 孤儿] + [f"双当前:{x}" for x in 双当前] + 半截["问题"]
        通过 = 0 if 问题 else 1
        说明 = "；".join(问题) if 问题 else "枢纽、链接、卫星引用与当前版贯穿互证通过，半截回滚零残留"
        conn.execute(
            "INSERT INTO 金库贯验(时刻, 枢纽数, 链接数, 卫星当前数, 是否通过, 说明) VALUES (?,?,?,?,?,?)",
            (此刻(), 枢纽数, 链接数, 卫星当前数, 通过, 说明),
        )
        conn.commit()
        return {
            "是否通过": bool(通过),
            "枢纽数": 枢纽数,
            "链接数": 链接数,
            "卫星当前数": 卫星当前数,
            "说明": 说明,
            "检项": 检项,
        }
    finally:
        conn.close()
