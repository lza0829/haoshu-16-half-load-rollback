from app.db import 连接


def 总览() -> dict:
    conn = 连接()
    try:
        def c(sql):
            return conn.execute(sql).fetchone()["c"]

        末 = conn.execute("SELECT * FROM 金库贯验 ORDER BY 编号 DESC LIMIT 1").fetchone()
        return {
            "号卡枢纽": c("SELECT COUNT(*) AS c FROM 枢纽_号卡"),
            "套餐枢纽": c("SELECT COUNT(*) AS c FROM 枢纽_套餐"),
            "客户枢纽": c("SELECT COUNT(*) AS c FROM 枢纽_客户"),
            "订购链接": c("SELECT COUNT(*) AS c FROM 链接_号卡套餐"),
            "实名链接": c("SELECT COUNT(*) AS c FROM 链接_号卡客户"),
            "卫星当前": sum(
                c(f"SELECT COUNT(*) AS c FROM {t} WHERE 是否当前=1")
                for t in ("卫星_号卡属性", "卫星_套餐属性", "卫星_客户属性", "卫星_订购属性")
            ),
            "装载批次": c("SELECT COUNT(*) AS c FROM 装载批次"),
            "隔离": c("SELECT COUNT(*) AS c FROM 隔离匣"),
            "末次贯验": dict(末) if 末 else None,
        }
    finally:
        conn.close()
