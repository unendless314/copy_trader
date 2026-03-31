"""
scripts/pnl_report.py

BTCUSDT 近似交易績效報告（簡化版）

資料來源：
- execution_results：只納入已被 Binance 接受的送單紀錄
- reconciliation_decisions：回補近似成交價格（優先 executable_price，否則 reference_price）

限制：
- 仍非真實成交帳本
- 不含手續費
- 不含真實滑價
- 僅適合作為近似績效觀察
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


ACCEPTED_STATUSES = ("NEW", "FILLED", "PARTIALLY_FILLED")


@dataclass
class TradeRecord:
    cycle_id: str
    timestamp: datetime
    side: str
    qty: Decimal
    price: Decimal
    amount: Decimal
    execution_status: str
    order_id: str
    price_source: str


def parse_args():
    parser = argparse.ArgumentParser(description="BTCUSDT 近似交易績效報告")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/copy_trading.db"),
        help="SQLite 資料庫路徑 (預設: data/copy_trading.db)",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSDT",
        help="交易對 (預設: BTCUSDT)",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="起始日期 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="結束日期 (YYYY-MM-DD)",
    )
    return parser.parse_args()


def get_db_connection(db_path: Path):
    if not db_path.exists():
        print(f"錯誤：資料庫檔案不存在: {db_path}", file=sys.stderr)
        sys.exit(1)
    return sqlite3.connect(db_path)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def load_trades(
    conn: sqlite3.Connection,
    symbol: str,
    since: str | None = None,
    until: str | None = None,
) -> tuple[list[TradeRecord], int]:
    accepted_placeholders = ", ".join("?" for _ in ACCEPTED_STATUSES)
    query = f"""
        SELECT
            e.cycle_id,
            e.created_at,
            e.action,
            e.requested_size,
            e.status,
            e.exchange_order_id,
            r.executable_price,
            r.reference_price
        FROM execution_results e
        LEFT JOIN reconciliation_decisions r
          ON r.cycle_id = e.cycle_id
         AND r.symbol = e.symbol
        WHERE e.symbol = ?
          AND e.status IN ({accepted_placeholders})
          AND e.exchange_order_id IS NOT NULL
    """
    params: list[Any] = [symbol, *ACCEPTED_STATUSES]

    if since:
        query += " AND date(e.created_at) >= date(?)"
        params.append(since)
    if until:
        query += " AND date(e.created_at) <= date(?)"
        params.append(until)

    query += " ORDER BY e.created_at ASC"

    rows = conn.execute(query, params).fetchall()

    trades = []
    skipped_rows = 0
    for cycle_id, created_at, action, qty_str, status, order_id, executable_price_str, reference_price_str in rows:
        price_str = executable_price_str or reference_price_str
        if price_str is None:
            skipped_rows += 1
            continue

        qty = Decimal(qty_str)
        price = Decimal(price_str)
        amount = qty * price
        trades.append(
            TradeRecord(
                cycle_id=cycle_id,
                timestamp=_parse_timestamp(created_at),
                side=action,
                qty=qty,
                price=price,
                amount=amount,
                execution_status=status,
                order_id=str(order_id),
                price_source="executable_price" if executable_price_str is not None else "reference_price",
            )
        )
    return trades, skipped_rows


def load_latest_mark_price(conn: sqlite3.Connection, symbol: str) -> Decimal | None:
    row = conn.execute(
        """
        SELECT executable_price, reference_price
        FROM reconciliation_decisions
        WHERE symbol = ?
          AND (executable_price IS NOT NULL OR reference_price IS NOT NULL)
        ORDER BY created_at DESC
        LIMIT 1
        """,
        [symbol],
    ).fetchone()

    if row is None:
        return None

    executable_price_str, reference_price_str = row
    price_str = executable_price_str or reference_price_str
    return Decimal(price_str) if price_str is not None else None


def compute_pnl(trades: list[TradeRecord], mark_price: Decimal | None = None):
    total_buy_qty = Decimal("0")
    total_buy_amount = Decimal("0")
    total_sell_qty = Decimal("0")
    total_sell_amount = Decimal("0")
    realized_pnl = Decimal("0")

    open_lots: list[tuple[Decimal, Decimal]] = []

    for trade in trades:
        signed_qty = trade.qty if trade.side == "BUY" else -trade.qty

        if trade.side == "BUY":
            total_buy_qty += trade.qty
            total_buy_amount += trade.amount
        else:
            total_sell_qty += trade.qty
            total_sell_amount += trade.amount

        remaining = signed_qty
        while remaining != 0 and open_lots and (remaining > 0) != (open_lots[0][0] > 0):
            lot_qty, lot_price = open_lots[0]
            matched_qty = min(abs(remaining), abs(lot_qty))

            if lot_qty > 0 and remaining < 0:
                realized_pnl += matched_qty * (trade.price - lot_price)
                lot_qty -= matched_qty
                remaining += matched_qty
            else:
                realized_pnl += matched_qty * (lot_price - trade.price)
                lot_qty += matched_qty
                remaining -= matched_qty

            if lot_qty == 0:
                open_lots.pop(0)
            else:
                open_lots[0] = (lot_qty, lot_price)

        if remaining != 0:
            open_lots.append((remaining, trade.price))

    avg_buy_price = total_buy_amount / total_buy_qty if total_buy_qty > 0 else Decimal("0")
    avg_sell_price = total_sell_amount / total_sell_qty if total_sell_qty > 0 else Decimal("0")

    zero = Decimal("0")
    open_long_qty = sum((qty for qty, _ in open_lots if qty > 0), start=zero)
    open_short_qty = -sum((qty for qty, _ in open_lots if qty < 0), start=zero)
    net_open_qty = sum((qty for qty, _ in open_lots), start=zero)
    open_cost_basis = sum((qty * price for qty, price in open_lots), start=zero)

    unrealized_pnl = None
    if mark_price is not None:
        unrealized_pnl = Decimal("0")
        for qty, price in open_lots:
            if qty > 0:
                unrealized_pnl += qty * (mark_price - price)
            else:
                unrealized_pnl += abs(qty) * (price - mark_price)

    return {
        "total_buy_qty": total_buy_qty,
        "total_buy_amount": total_buy_amount,
        "total_sell_qty": total_sell_qty,
        "total_sell_amount": total_sell_amount,
        "avg_buy_price": avg_buy_price,
        "avg_sell_price": avg_sell_price,
        "realized_pnl": realized_pnl,
        "open_long_qty": open_long_qty,
        "open_short_qty": open_short_qty,
        "net_open_qty": net_open_qty,
        "open_cost_basis": open_cost_basis,
        "unrealized_pnl": unrealized_pnl,
        "open_lots": open_lots,
        "mark_price": mark_price,
    }


def format_currency(amount: Decimal) -> str:
    return f"${amount:,.2f}"


def format_qty(qty: Decimal) -> str:
    return f"{qty.normalize():f}"


def print_report(
    trades: list[TradeRecord],
    pnl: dict,
    skipped_rows: int,
    since: str | None = None,
    until: str | None = None,
):
    date_range = f"{trades[0].timestamp.strftime('%Y-%m-%d %H:%M')} ~ {trades[-1].timestamp.strftime('%Y-%m-%d %H:%M')}"
    if since or until:
        date_range = f"{since or '最早'} ~ {until or '最新'} (已過濾)"

    print(f"\n{'=' * 72}")
    print("  近似交易績效報告")
    print(f"{'=' * 72}")
    print(f"  資料時間：{date_range}")
    print(f"  納入交易次數：{len(trades)}")
    print("  資料口徑：execution_results 已接受送單 + reconciliation_decisions 近似價格")
    print("  注意：不含手續費、真實滑價、逐筆成交回報")
    if skipped_rows:
        print(f"  略過筆數：{skipped_rows}（缺少可用價格）")
    print(f"{'=' * 72}")

    buy_count = sum(1 for trade in trades if trade.side == "BUY")
    sell_count = sum(1 for trade in trades if trade.side == "SELL")

    print("\n【買入統計】")
    print(f"  平均買入價：{format_currency(pnl['avg_buy_price'])}")
    print(f"  買入次數：{buy_count} / 總量：{format_qty(pnl['total_buy_qty'])} BTC")

    print("\n【賣出統計】")
    print(f"  平均賣出價：{format_currency(pnl['avg_sell_price'])}")
    print(f"  賣出次數：{sell_count} / 總量：{format_qty(pnl['total_sell_qty'])} BTC")

    print("\n【已實現損益】")
    print(f"  {format_currency(pnl['realized_pnl'])}")

    print("\n【未平倉部位】")
    if pnl["net_open_qty"] > 0:
        print(f"  淨部位：多 {format_qty(pnl['net_open_qty'])} BTC")
    elif pnl["net_open_qty"] < 0:
        print(f"  淨部位：空 {format_qty(abs(pnl['net_open_qty']))} BTC")
    else:
        print("  淨部位：0 BTC")
    print(f"  未平多單：{format_qty(pnl['open_long_qty'])} BTC")
    print(f"  未平空單：{format_qty(pnl['open_short_qty'])} BTC")

    if pnl["mark_price"] is not None and pnl["unrealized_pnl"] is not None:
        print("\n【未實現損益（近似）】")
        print(f"  估值價格：{format_currency(pnl['mark_price'])}")
        print(f"  {format_currency(pnl['unrealized_pnl'])}")

    print("\n【交易明細】")
    print(f"{'-' * 72}")
    print(f"  {'時間':<20} {'方向':<6} {'數量(BTC)':<14} {'近似價格':<12} {'狀態':<18}")
    print(f"{'-' * 72}")
    for trade in trades:
        status = f"{trade.execution_status}/{trade.price_source}"
        print(
            f"  {trade.timestamp.strftime('%Y-%m-%d %H:%M'):<20} "
            f"{trade.side:<6} "
            f"{format_qty(trade.qty):<14} "
            f"{format_currency(trade.price):<12} "
            f"{status:<18}"
        )
    print(f"{'-' * 72}")
    print()


def main():
    args = parse_args()
    db_path = args.db.resolve()

    conn = get_db_connection(db_path)
    try:
        trades, skipped_rows = load_trades(conn, args.symbol, args.since, args.until)
        if not trades:
            print(
                "找不到可用交易紀錄（可能沒有已接受送單，或缺少近似價格）",
                file=sys.stderr,
            )
            sys.exit(1)

        mark_price = load_latest_mark_price(conn, args.symbol)
        pnl = compute_pnl(trades, mark_price=mark_price)
        print_report(trades, pnl, skipped_rows, args.since, args.until)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
