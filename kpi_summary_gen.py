"""
kpi_summary.py
Builds a KPI summary table for a spares shop: current value, previous period,
change, and a plain-language explanation for each KPI.

Inputs (same folder as this script):
    sales_customers.csv   date, product_id, quantity_sold, customer_id
    inventory.csv         product_id, ..., unit_price_kes, ...
Outputs:
    kpi_summary.csv    the KPI table (with a Status column)
    kpi_summary.html   the same table colour-coded: green = good, amber = caution,
                       red = watch, grey = no comparison available

Definitions (also documented in the README):
  - Periods: three rolling 30-day windows ending on the last sales date
             current, previous, earlier
  - Revenue: quantity_sold x unit_price_kes
  - Growth rate: (this period revenue - previous period revenue) / previous x 100
  - Churn rate: customers who bought in the previous period but NOT in the
                current one, divided by customers in the previous period x 100
  - Order: all items one customer buys on one day
  - Average order value: revenue / number of orders
"""

import textwrap
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent
WINDOW_DAYS = 30


# ---------- loading ----------

def load_data(sales_path, inventory_path):
    sales = pd.read_csv(sales_path, parse_dates=["date"])
    inventory = pd.read_csv(inventory_path)

    df = sales.merge(inventory[["product_id", "unit_price_kes"]], on="product_id", how="left")

    unmatched = df["unit_price_kes"].isna().sum()
    if unmatched:
        print(f"Warning: {unmatched} sales rows have no matching product and were dropped")
        df = df.dropna(subset=["unit_price_kes"])

    df["revenue_kes"] = df["quantity_sold"] * df["unit_price_kes"]
    return df


def split_periods(df):
    """Split data into current / previous / earlier 30-day windows."""
    end = df["date"].max().normalize()
    periods = {}
    for name, k in [("current", 0), ("previous", 1), ("earlier", 2)]:
        p_end = end - pd.Timedelta(days=WINDOW_DAYS * k)
        p_start = p_end - pd.Timedelta(days=WINDOW_DAYS - 1)
        mask = (df["date"] >= p_start) & (df["date"] <= p_end)
        periods[name] = {"data": df[mask], "start": p_start, "end": p_end}
    return periods


# ---------- KPI calculations ----------

def total_revenue(d):
    return d["revenue_kes"].sum()


def order_count(d):
    return d.groupby(["date", "customer_id"]).ngroups


def avg_order_value(d):
    n = order_count(d)
    return total_revenue(d) / n if n else 0


def growth_pct(current, previous):
    return (current - previous) / previous * 100 if previous else 0


def churn_pct(previous_df, current_df):
    before = set(previous_df["customer_id"])
    now = set(current_df["customer_id"])
    return len(before - now) / len(before) * 100 if before else 0


# ---------- formatting and explanations ----------

def kes(value):
    return f"KES {value:,.0f}"


def pct(value):
    return f"{value:.1f}%"


def signed(value, unit=""):
    return f"{value:+.1f}{unit}"


STATUS_COLOURS = {
    "Good": "#c8e6c9",     # green
    "Caution": "#fff3b0",  # amber
    "Watch": "#ffcdd2",    # red
    "Neutral": "#e0e0e0",  # grey
}


def build_table(periods):
    cur, prev, earlier = (periods[k]["data"] for k in ("current", "previous", "earlier"))

    # The growth and churn comparisons need a third period. If the data does not
    # reach back that far, show "n/a" instead of a misleading 0%.
    has_earlier = len(earlier) > 0

    rev_cur, rev_prev, rev_earlier = total_revenue(cur), total_revenue(prev), total_revenue(earlier)
    growth_cur = growth_pct(rev_cur, rev_prev)
    churn_cur = churn_pct(prev, cur)
    aov_cur, aov_prev = avg_order_value(cur), avg_order_value(prev)

    rev_change = growth_pct(rev_cur, rev_prev)
    aov_change = aov_cur - aov_prev

    if has_earlier:
        growth_prev = growth_pct(rev_prev, rev_earlier)
        churn_prev = churn_pct(earlier, prev)
        growth_change = growth_cur - growth_prev
        churn_change = churn_cur - churn_prev

        growth_prev_text, growth_change_text = pct(growth_prev), signed(growth_change, "pp")
        churn_prev_text, churn_change_text = pct(churn_prev), signed(churn_change, "pp")

        if growth_cur < 0:
            growth_note, growth_status = "Revenue is shrinking, so find out why.", "Watch"
        elif growth_change >= 0:
            growth_note, growth_status = "Growth is speeding up compared with last period.", "Good"
        else:
            growth_note, growth_status = "Revenue is still growing, but more slowly than last period.", "Caution"

        if churn_change > 0:
            churn_note, churn_status = "More customers stopped buying than last period. Watch this.", "Watch"
        elif churn_change < 0:
            churn_note, churn_status = "Fewer customers are leaving than last period.", "Good"
        else:
            churn_note, churn_status = "Customer loss is unchanged from last period.", "Neutral"
    else:
        growth_prev_text = growth_change_text = "n/a"
        churn_prev_text = churn_change_text = "n/a"
        direction = "grew" if growth_cur >= 0 else "shrank"
        growth_note = (
            f"Revenue {direction} {abs(growth_cur):.1f}% this period. There is no earlier "
            "period to compare with, so we can't say if growth is speeding up."
        )
        growth_status = "Neutral"
        churn_note = (
            f"{churn_cur:.1f}% of last period's customers did not buy this period. "
            "There is no earlier period to compare with."
        )
        churn_status = "Neutral"

    rows = [
        {
            "KPI": "Monthly revenue",
            "Current": kes(rev_cur),
            "Previous": kes(rev_prev),
            "Change": signed(rev_change, "%"),
            "Status": "Good" if rev_change >= 0 else "Watch",
            "What it means": (
                f"Sales {'rose' if rev_change >= 0 else 'fell'} "
                f"{abs(rev_change):.1f}% compared with the previous 30 days."
            ),
        },
        {
            "KPI": "Growth rate",
            "Current": pct(growth_cur),
            "Previous": growth_prev_text,
            "Change": growth_change_text,
            "Status": growth_status,
            "What it means": growth_note,
        },
        {
            "KPI": "Churn rate",
            "Current": pct(churn_cur),
            "Previous": churn_prev_text,
            "Change": churn_change_text,
            "Status": churn_status,
            "What it means": churn_note,
        },
        {
            "KPI": "Avg order value",
            "Current": kes(aov_cur),
            "Previous": kes(aov_prev),
            "Change": f"{aov_change:+,.0f} KES",
            "Status": "Good" if aov_change >= 0 else "Watch",
            "What it means": (
                f"Customers spend {'more' if aov_change >= 0 else 'less'} "
                f"per order than last period."
            ),
        },
    ]
    return pd.DataFrame(rows)


# ---------- output ----------

def print_table(table):
    """Compact table first, then the explanations as wrapped lines."""
    print(table[["KPI", "Current", "Previous", "Change", "Status"]].to_string(index=False))
    print("\nWhat it means:")
    for _, row in table.iterrows():
        text = f"- {row['KPI']}: {row['What it means']}"
        print(textwrap.fill(text, width=88, subsequent_indent="  "))


def save_html(table, out_path):
    """Save a colour-coded version of the table (uses pandas Styler)."""
    def colour_cells(row):
        style = f"background-color: {STATUS_COLOURS[row['Status']]}; font-weight: bold"
        return [style if col in ("Change", "Status") else "" for col in row.index]

    styler = (
        table.style
        .apply(colour_cells, axis=1)
        .hide(axis="index")
        .set_caption("KPI Summary")
        .set_table_styles([
            {"selector": "", "props": "border-collapse: collapse; font-family: Arial, sans-serif; width: 100%;"},
            {"selector": "caption", "props": "font-size: 20px; font-weight: bold; margin-bottom: 10px;"},
            {"selector": "th", "props": "background-color: #1f4e79; color: white; padding: 8px 12px; text-align: left;"},
            {"selector": "td", "props": "padding: 8px 12px; border-bottom: 1px solid #ddd;"},
            # keep the number columns on one line (the last column is free to wrap)
            {"selector": "td:nth-child(-n+5)", "props": "white-space: nowrap;"},
        ])
    )
    html = "<meta charset='utf-8'>" + styler.to_html()
    Path(out_path).write_text(html, encoding="utf-8")


def run(sales_path, inventory_path, out_csv, out_html):
    df = load_data(sales_path, inventory_path)
    periods = split_periods(df)

    if len(df) and (df["date"].max() - df["date"].min()).days + 1 < WINDOW_DAYS * 3:
        print("Warning: less than 90 days of data, so the 'earlier' period is partial")

    print("Periods (30 days each):")
    for name, p in periods.items():
        print(f"  {name:<9} {p['start'].date()} to {p['end'].date()}  ({len(p['data'])} sales rows)")

    table = build_table(periods)
    table.to_csv(out_csv, index=False)

    print("\nKPI SUMMARY")
    print_table(table)
    print(f"\nSaved to {out_csv}")

    try:
        save_html(table, out_html)
        print(f"Colour-coded version saved to {out_html}")
    except ImportError:
        print("Could not create the HTML version. Run: pip install jinja2")
    return table


if __name__ == "__main__":
    run(
        BASE_DIR / "sales_customers.csv",
        BASE_DIR / "inventory.csv",
        BASE_DIR / "kpi_summary.csv",
        BASE_DIR / "kpi_summary.html",
    )
