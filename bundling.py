"""
Bundling helpers for near-expiry and dead-stock recommendations.
"""

from typing import Dict, List, Tuple


def get_top_sellers_by_department(conn, months_back: int = 3, limit: int = 3) -> Dict[str, List[str]]:
    """Return top-selling item names per department for recent months."""
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT i.department, i.item_name, SUM(st.quantity_sold) as total
        FROM sales_transactions st
        JOIN items i ON st.item_id = i.item_id
        WHERE st.sale_date >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
        GROUP BY i.department, st.item_id
        ORDER BY i.department, total DESC
        """,
        (months_back,),
    )
    rows = cur.fetchall()
    cur.close()

    by_dept: Dict[str, List[str]] = {}
    for r in rows:
        dept = r.get("department") or "Unknown"
        if dept not in by_dept:
            by_dept[dept] = []
        if len(by_dept[dept]) < limit:
            by_dept[dept].append(r["item_name"])
    return by_dept


def get_top_sellers_by_type(conn, months_back: int = 3, limit: int = 3) -> Dict[str, List[str]]:
    """Return top-selling item names per type for recent months."""
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT i.type, i.item_name, SUM(st.quantity_sold) as total
        FROM sales_transactions st
        JOIN items i ON st.item_id = i.item_id
        WHERE st.sale_date >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
        GROUP BY i.type, st.item_id
        ORDER BY i.type, total DESC
        """,
        (months_back,),
    )
    rows = cur.fetchall()
    cur.close()

    by_type: Dict[str, List[str]] = {}
    for r in rows:
        item_type = r.get("type") or "Unknown"
        if item_type not in by_type:
            by_type[item_type] = []
        if len(by_type[item_type]) < limit:
            by_type[item_type].append(r["item_name"])
    return by_type


def get_top_sellers_global(conn, months_back: int = 3, limit: int = 5) -> List[str]:
    """Return top-selling item names overall for recent months."""
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT i.item_name, SUM(st.quantity_sold) as total
        FROM sales_transactions st
        JOIN items i ON st.item_id = i.item_id
        WHERE st.sale_date >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
        GROUP BY st.item_id
        ORDER BY total DESC
        LIMIT %s
        """,
        (months_back, limit),
    )
    rows = cur.fetchall()
    cur.close()
    return [r["item_name"] for r in rows]


def _pick_candidates(source: List[str], exclude: str, limit: int = 2) -> List[str]:
    return [n for n in source if n != exclude][:limit]


def build_bundle_candidates(
    item_name: str,
    department: str,
    item_type: str,
    dept_top: Dict[str, List[str]],
    type_top: Dict[str, List[str]],
    global_top: List[str],
    limit: int = 2,
) -> List[str]:
    """
    Smart bundling:
    1) Same department best-sellers
    2) Complementary department based on type/department
    3) Same type best-sellers
    4) Global best-sellers
    """
    department = department or "Unknown"
    item_type = item_type or "Unknown"

    # Complementary mapping (tune as needed for your catalog)
    complementary_dept = {
        "Beverages": "Snacks",
        "Food": "Beverages",
        "Frozen": "Sauces & Condiments",
        "Personal Care": "Household",
        "Household": "Personal Care",
        "Stationery": "Office Supplies",
        "Office Supplies": "Stationery",
    }

    candidates: List[str] = []

    # 1) Same department
    candidates += _pick_candidates(dept_top.get(department, []), item_name, limit)

    # 2) Complementary department
    if len(candidates) < limit:
        comp = complementary_dept.get(department)
        if comp:
            candidates += _pick_candidates(dept_top.get(comp, []), item_name, limit - len(candidates))

    # 3) Same type
    if len(candidates) < limit:
        candidates += _pick_candidates(type_top.get(item_type, []), item_name, limit - len(candidates))

    # 4) Global
    if len(candidates) < limit:
        candidates += _pick_candidates(global_top, item_name, limit - len(candidates))

    return candidates[:limit]
