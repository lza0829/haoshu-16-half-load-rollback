from app.db import 连接
from app.seed import 此刻


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
        ]
        问题 = 缺链 + [f"孤儿卫星:{x}" for x in 孤儿] + [f"双当前:{x}" for x in 双当前]
        通过 = 0 if 问题 else 1
        说明 = "；".join(问题) if 问题 else "枢纽、链接、卫星引用与当前版贯穿互证通过"
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
