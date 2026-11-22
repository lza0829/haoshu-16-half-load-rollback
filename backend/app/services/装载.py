"""装载服务 · 半截装载回滚口径甲：单事务原子回滚。

一批正式写库（枢纽→链接→卫星）与「装载事务日志、批次成功标志」同属一个事务：
任一步失败整体回滚，正式三族该批增量自然为零；随后独立小事务把批次记为失败。
不存在段间提交，故无补偿器、无清扫路径、无「补偿未完却标终结」窗口；
批号一次性，同批号重试/补偿并发直接被拒，重试须换新批号。
"""
import json
import sqlite3
import uuid
from typing import Any

from app.db import 连接
from app.seed import 哈希键, 载荷哈希, 此刻


def 装一批(体: dict[str, Any]) -> dict[str, Any]:
    """顺序：枢纽 → 链接 → 卫星。任一步失败整批回滚，批次记失败。"""
    装载日 = str(体.get("装载日") or "").strip()
    if not 装载日:
        return {"结果": "拒绝", "说明": "缺装载日"}
    枢纽 = 体.get("枢纽") or {}
    链接 = 体.get("链接") or {}
    卫星 = 体.get("卫星") or {}
    批号 = str(体.get("批次编号") or f"批-{uuid.uuid4().hex[:10]}")
    事务号 = uuid.uuid4().hex

    # ① 认领批号（独立小事务）：批号一次性，杜绝同批重试/补偿交错
    conn = 连接()
    try:
        try:
            conn.execute(
                "INSERT INTO 装载批次(编号, 装载日, 时刻, 状态, 事务号) VALUES (?,?,?,'装载中',?)",
                (批号, 装载日, 此刻(), 事务号),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            return {"结果": "拒绝", "说明": f"批次编号已存在:{批号}（批号一次性，重试须换新批号）"}
    finally:
        conn.close()

    报 = {"枢纽": 0, "链接": 0, "卫星": 0, "跳过": 0, "明细": []}
    conn = 连接()
    try:
        # ② 单事务装载：正式三族 + 事务日志 + 批次成功标志同生共死
        for 类, 表, 前缀 in (
            ("号卡", "枢纽_号卡", "号卡"),
            ("套餐", "枢纽_套餐", "套餐"),
            ("客户", "枢纽_客户", "客户"),
        ):
            for 项 in 枢纽.get(类) or []:
                业务键 = str(项.get("业务键") or "").strip()
                if not 业务键:
                    报["跳过"] += 1
                    continue
                h = 哈希键(前缀, 业务键)
                旧 = conn.execute(f"SELECT 1 FROM {表} WHERE 业务键=?", (业务键,)).fetchone()
                if 旧:
                    报["跳过"] += 1
                    报["明细"].append({"类": f"枢纽-{类}", "业务键": 业务键, "结果": "已存在"})
                    continue
                conn.execute(
                    f"INSERT INTO {表}(哈希键, 业务键, 装载日, 批号) VALUES (?,?,?,?)",
                    (h, 业务键, 装载日, 批号),
                )
                报["枢纽"] += 1
                报["明细"].append({"类": f"枢纽-{类}", "业务键": 业务键, "哈希键": h, "结果": "新开"})

        def 取枢纽哈希(表, 业务键):
            r = conn.execute(f"SELECT 哈希键 FROM {表} WHERE 业务键=?", (业务键,)).fetchone()
            return r["哈希键"] if r else None

        # 链接 号卡-套餐
        for 项 in 链接.get("号卡套餐") or []:
            号 = str(项.get("号卡业务键") or "").strip()
            套 = str(项.get("套餐业务键") or "").strip()
            hk卡 = 取枢纽哈希("枢纽_号卡", 号)
            hk套 = 取枢纽哈希("枢纽_套餐", 套)
            if not hk卡 or not hk套:
                raise ValueError(f"链接号卡套餐缺枢纽: {号}/{套}")
            lh = 哈希键("链订购", hk卡, hk套)
            if conn.execute("SELECT 1 FROM 链接_号卡套餐 WHERE 哈希键=?", (lh,)).fetchone():
                报["跳过"] += 1
                continue
            conn.execute(
                "INSERT INTO 链接_号卡套餐(哈希键, 号卡哈希, 套餐哈希, 装载日, 批号) VALUES (?,?,?,?,?)",
                (lh, hk卡, hk套, 装载日, 批号),
            )
            报["链接"] += 1

        # 链接 号卡-客户
        for 项 in 链接.get("号卡客户") or []:
            号 = str(项.get("号卡业务键") or "").strip()
            客 = str(项.get("客户业务键") or "").strip()
            hk卡 = 取枢纽哈希("枢纽_号卡", 号)
            hk客 = 取枢纽哈希("枢纽_客户", 客)
            if not hk卡 or not hk客:
                raise ValueError(f"链接号卡客户缺枢纽: {号}/{客}")
            lh = 哈希键("链实名", hk卡, hk客)
            if conn.execute("SELECT 1 FROM 链接_号卡客户 WHERE 哈希键=?", (lh,)).fetchone():
                报["跳过"] += 1
                continue
            conn.execute(
                "INSERT INTO 链接_号卡客户(哈希键, 号卡哈希, 客户哈希, 装载日, 批号) VALUES (?,?,?,?,?)",
                (lh, hk卡, hk客, 装载日, 批号),
            )
            报["链接"] += 1

        def 开卫星(表, 父列, 父哈希, 属性: dict):
            ph = 载荷哈希(属性)
            当前 = conn.execute(
                f"SELECT 编号, 载荷哈希 FROM {表} WHERE {父列}=? AND 是否当前=1",
                (父哈希,),
            ).fetchone()
            if 当前 and 当前["载荷哈希"] == ph:
                报["跳过"] += 1
                return
            if 当前:
                conn.execute(f"UPDATE {表} SET 是否当前=0 WHERE 编号=?", (当前["编号"],))
            conn.execute(
                f"INSERT INTO {表}({父列}, 装载日, 载荷哈希, 属性, 是否当前, 批号) VALUES (?,?,?,?,1,?)",
                (父哈希, 装载日, ph, json.dumps(属性, ensure_ascii=False), 批号),
            )
            报["卫星"] += 1

        for 项 in 卫星.get("号卡") or []:
            号 = str(项.get("业务键") or "").strip()
            h = 取枢纽哈希("枢纽_号卡", 号)
            if not h:
                raise ValueError(f"卫星号卡无枢纽: {号}")
            开卫星("卫星_号卡属性", "号卡哈希", h, 项.get("属性") or {})

        for 项 in 卫星.get("套餐") or []:
            套 = str(项.get("业务键") or "").strip()
            h = 取枢纽哈希("枢纽_套餐", 套)
            if not h:
                raise ValueError(f"卫星套餐无枢纽: {套}")
            开卫星("卫星_套餐属性", "套餐哈希", h, 项.get("属性") or {})

        for 项 in 卫星.get("客户") or []:
            客 = str(项.get("业务键") or "").strip()
            h = 取枢纽哈希("枢纽_客户", 客)
            if not h:
                raise ValueError(f"卫星客户无枢纽: {客}")
            开卫星("卫星_客户属性", "客户哈希", h, 项.get("属性") or {})

        for 项 in 卫星.get("订购") or []:
            号 = str(项.get("号卡业务键") or "").strip()
            套 = str(项.get("套餐业务键") or "").strip()
            hk卡 = 取枢纽哈希("枢纽_号卡", 号)
            hk套 = 取枢纽哈希("枢纽_套餐", 套)
            if not hk卡 or not hk套:
                raise ValueError(f"卫星订购无链接端: {号}/{套}")
            lh = 哈希键("链订购", hk卡, hk套)
            if not conn.execute("SELECT 1 FROM 链接_号卡套餐 WHERE 哈希键=?", (lh,)).fetchone():
                raise ValueError(f"卫星订购无链接: {号}/{套}")
            开卫星("卫星_订购属性", "链接哈希", lh, 项.get("属性") or {})

        # 同事务终结：提交证据（装载事务日志）与批次成功标志随正式数据同生共死
        conn.execute(
            "INSERT INTO 装载事务(事务号, 批号, 装载日, 提交时刻) VALUES (?,?,?,?)",
            (事务号, 批号, 装载日, 此刻()),
        )
        cur = conn.execute(
            "UPDATE 装载批次 SET 状态='成功', 报告=? WHERE 编号=? AND 状态='装载中'",
            (json.dumps(报, ensure_ascii=False), 批号),
        )
        if cur.rowcount != 1:
            raise RuntimeError(f"批次{批号}状态被并发改写，拒绝终结")
        conn.commit()
        return {"结果": "成功", "批次编号": 批号, "装载日": 装载日, "事务号": 事务号, "报告": 报}
    except Exception as e:
        conn.rollback()  # 正式三族该批增量整体归零，不存在段间提交残留
        误 = str(e)
    finally:
        conn.close()

    # ③ 失败记账（独立小事务）：批次非成功 + 隔离匣留证；
    # 若连记账也失败，批次悬挂「装载中」，贯验见之失败闭。
    conn2 = 连接()
    try:
        conn2.execute(
            "UPDATE 装载批次 SET 状态='失败', 报告=? WHERE 编号=? AND 状态='装载中'",
            (json.dumps({"错误": 误}, ensure_ascii=False), 批号),
        )
        conn2.execute(
            "INSERT INTO 隔离匣(原因, 载荷, 时刻) VALUES (?,?,?)",
            (误, json.dumps(体, ensure_ascii=False)[:2000], 此刻()),
        )
        conn2.commit()
    except Exception as e2:
        conn2.rollback()
        return {"结果": "失败", "批次编号": 批号, "说明": f"{误}；失败记账亦失败:{e2}（批次悬挂装载中，贯验将失败闭）"}
    finally:
        conn2.close()
    return {"结果": "失败", "批次编号": 批号, "说明": 误}
