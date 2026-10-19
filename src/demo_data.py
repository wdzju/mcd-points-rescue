"""Synthetic, offline fixtures so the pipeline runs without a live token.

IMPORTANT
---------
Every value here is fabricated for demonstration only. Item names mirror
publicly known McDonald's China menu items so the matching logic is exercised
on realistic strings, but balances, prices and stock counts are invented and
carry no relationship to any real account. Nothing here is read from the
McDonald's MCP Server; `--live` replaces it entirely.

Field names and nesting deliberately mirror the REAL envelope shapes observed
on mcp.mcd.cn, so demo mode exercises exactly the same code paths as live mode.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

DISCLAIMER = "以下数据为脱敏合成样例，仅用于演示算法，不代表任何真实账户余额或官方价格。"


def fake_account() -> Dict[str, Any]:
    """Mirrors query-my-account → data (note the API's "Mouth" spelling)."""
    return {
        "availablePoint": "1248.5",
        "accountId": "DEMO-0000-0000-0000-DEMO00000000",
        "accumulativePoint": "5358.7",
        "currency": "麦享会积分",
        "currentMouthExpirePoint": "520",
        "expiredPoint": "2355.2",
        "frozenPoint": "0",
        "lastMouthExpirePoint": "120",
        "nextMouthExpirePoint": "60",
        "usedPoint": "2447",
    }


def fake_menu() -> Dict[str, Any]:
    """Mirrors query-meals → data.meals (a code → detail map)."""
    meals = {
        "M01": {"name": "巨无霸", "currentPrice": "26.0", "originalPrice": "26.0"},
        "M02": {"name": "板烧鸡腿堡", "currentPrice": "24.0", "originalPrice": "24.0"},
        "M03": {"name": "麦辣鸡腿汉堡", "currentPrice": "23.0", "originalPrice": "23.0"},
        "M04": {"name": "双层深海鳕鱼堡", "currentPrice": "24.0", "originalPrice": "24.0"},
        "M05": {"name": "麦香鱼", "currentPrice": "22.5", "originalPrice": "22.5"},
        "M06": {"name": "经典麦旋风", "currentPrice": "15.0", "originalPrice": "15.0"},
        "M07": {"name": "可乐", "currentPrice": "9.5", "originalPrice": "9.5"},
        "M08": {"name": "雪碧", "currentPrice": "9.5", "originalPrice": "9.5"},
        "M09": {"name": "薯条", "currentPrice": "14.5", "originalPrice": "14.5"},
        "M10": {"name": "麦乐鸡", "currentPrice": "14.5", "originalPrice": "14.5"},
        "M11": {"name": "玉米杯", "currentPrice": "13.0", "originalPrice": "13.0"},
        "M12": {"name": "派", "currentPrice": "8.5", "originalPrice": "8.5"},
        "M13": {"name": "圆筒冰淇淋", "currentPrice": "5.0", "originalPrice": "5.0"},
        "M14": {"name": "麦辣鸡翅", "currentPrice": "14.5", "originalPrice": "14.5"},
        "M15": {"name": "麦麦脆汁鸡1块", "currentPrice": "15.0", "originalPrice": "15.0"},
        "S01": {"name": "巨无霸四件套", "currentPrice": "32.0", "originalPrice": "59.0"},
        "S02": {"name": "板烧鸡腿堡四件套", "currentPrice": "28.0", "originalPrice": "58.0"},
        "S03": {"name": "麦辣鸡腿堡四件套", "currentPrice": "28.0", "originalPrice": "58.0"},
        "S04": {"name": "巨无霸三件套", "currentPrice": "37.0", "originalPrice": "50.5"},
        "S05": {"name": "板烧鸡腿堡三件套", "currentPrice": "35.0", "originalPrice": "48.5"},
        "S06": {"name": "麦辣鸡腿汉堡三件套", "currentPrice": "34.0", "originalPrice": "47.5"},
        "S07": {"name": "双层深海鳕鱼堡三件套", "currentPrice": "35.0", "originalPrice": "48.5"},
        "S08": {"name": "开心亲子双人餐", "currentPrice": "59.5", "originalPrice": "59.5"},
    }
    codes = list(meals)
    categories = [
        {"name": "汉堡", "meals": [{"code": c} for c in codes[:6]]},
        {"name": "小食甜品", "meals": [{"code": c} for c in codes[6:16]]},
        {"name": "套餐", "meals": [{"code": c} for c in codes[16:]]},
    ]
    return {"categories": categories, "meals": meals}


def fake_mall_products() -> List[Dict[str, Any]]:
    """Mirrors mall-points-products → data (a list of SPU rows).

    `downTime` is the last moment the item can still be redeemed — the input
    behind the countdown warning.
    """
    soon = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    later = (date.today() + timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
    return [
        {"spuName": "为随心配五大巨星“应援”1积分兑换活动", "spuId": 1001, "point": "1", "price": "0", "catName": "到店专用", "status": 2, "downTime": soon},
        {"spuName": "6.9元可乐麦炫酷", "spuId": 1002, "point": "50", "price": "0", "catName": "到店专用", "status": 2, "downTime": later},
        {"spuName": "5.9元香芋派/菠萝派任选", "spuId": 1003, "point": "50", "price": "0", "catName": "到店专用", "status": 2, "downTime": later},
        {"spuName": "10.9元指定小食任选", "spuId": 1004, "point": "100", "price": "0", "catName": "到店专用", "status": 2, "downTime": later},
        {"spuName": "18.8元板烧鸡腿堡两件套", "spuId": 1005, "point": "100", "price": "0", "catName": "到店专用", "status": 2, "downTime": later},
        {"spuName": "18.8元2份麦辣鸡翅", "spuId": 1006, "point": "200", "price": "0", "catName": "到店专用", "status": 2, "downTime": later},
        {"spuName": "16.9元中薯麦乐鸡组合", "spuId": 1007, "point": "200", "price": "0", "catName": "到店专用", "status": 2, "downTime": later},
        {"spuName": "17.9元板烧可乐组合", "spuId": 1008, "point": "500", "price": "0", "catName": "到店专用", "status": 2, "downTime": later},
        {"spuName": "22.8元2份麦辣鸡腿堡", "spuId": 1009, "point": "500", "price": "0", "catName": "到店专用", "status": 2, "downTime": later},
        {"spuName": "28.9元板烧四件套", "spuId": 1010, "point": "800", "price": "0", "catName": "到店专用", "status": 2, "downTime": later},
        {"spuName": "21.9元巨无霸可乐组合", "spuId": 1011, "point": "800", "price": "0", "catName": "到店专用", "status": 2, "downTime": later},
        {"spuName": "麦当劳小食四件套", "spuId": 1012, "point": "300", "price": "0", "catName": "到店专用", "status": 2, "downTime": later},
        {"spuName": "罗技键鼠套装", "spuId": 2001, "point": "6666", "price": "0", "catName": "玩具", "status": 2, "downTime": later},
        {"spuName": "麦当劳亲子读书会", "spuId": 3001, "point": "0", "price": "45", "catName": "读书会", "status": 2, "downTime": later},
    ]


def fake_lottery() -> Dict[str, Any]:
    """Mirrors query-lottery-info → data. No per-prize odds are published."""
    return {
        "status": {"code": "SUCCESS", "message": "成功"},
        "activityCode": "demo",
        "activityStatusText": "进行中",
        "activityName": "麦麦积分抽奖（样例）",
        "drawPoint": "24",
        "drawTypeText": "消耗积分抽奖",
        "availablePoint": "1248.5",
        "drawDecision": {"resourceEligible": True, "nextConsumption": {"type": "POINTS", "points": "24"}},
        "prizes": [
            {"name": "下单立减3元券", "typeText": "优惠券"},
            {"name": "下单立减2元券", "typeText": "优惠券"},
            {"name": "下单立减1元券", "typeText": "优惠券"},
            {"name": "板烧三件套5折券", "typeText": "优惠券"},
            {"name": "麦辣三件套5折券", "typeText": "优惠券"},
            {"name": "双层鳕鱼三件套6折券", "typeText": "优惠券"},
            {"name": "麦旋风5折券", "typeText": "优惠券"},
            {"name": "30积分", "typeText": "积分奖"},
        ],
    }


def fake_my_prizes() -> Dict[str, Any]:
    """Mirrors query-my-prizes → data."""
    today = date.today()
    return {
        "status": {"code": "SUCCESS", "message": "成功"},
        "prizes": [
            {"name": "麦旋风5折券", "prizeTypeText": "优惠券", "recordTime": (today - timedelta(days=9)).strftime("%Y-%m-%d"), "statusText": "已失效"},
            {"name": "圆筒冰淇淋4折优惠券", "prizeTypeText": "优惠券", "recordTime": (today - timedelta(days=14)).strftime("%Y-%m-%d"), "statusText": "已失效"},
            {"name": "下单立减1元券", "prizeTypeText": "优惠券", "recordTime": (today - timedelta(days=21)).strftime("%Y-%m-%d"), "statusText": "可用"},
            {"name": "30积分", "prizeTypeText": "积分奖", "recordTime": (today - timedelta(days=30)).strftime("%Y-%m-%d"), "statusText": "已使用"},
        ],
        "hasMore": False,
    }
