from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd


OUT = Path.home() / "Downloads"

BASE_DATE = datetime(
    2026,
    8,
    26,
    10,
    0,
)


# ============================================================
# COMMON DATA
# ============================================================

orders = []

amounts = [
    12500.00,
    18450.00,
    9200.00,
    26750.50,
    14800.75,
    32100.00,
    7850.25,
    45990.00,
    11325.40,
    27600.00,
    6325.00,
    38990.90,
]

customers = [
    "Alpha Retail",
    "Beta Stores",
    "Gamma Foods",
    "Delta Mart",
    "Epsilon Tech",
    "Zeta Retail",
    "Eta Fashion",
    "Theta Electronics",
    "Iota Foods",
    "Kappa Market",
    "Lambda Books",
    "Mu Hardware",
]


for i, amount in enumerate(
    amounts,
    start=1,
):

    orders.append(
        {
            "invoice_id": f"INV-DEMO-{i:03d}",
            "order_id": f"ORD-DEMO-{i:03d}",
            "amount": amount,
            "date": BASE_DATE
            + timedelta(minutes=(i - 1) * 11),
            "customer": customers[i - 1],
        }
    )


# ============================================================
# 1. INVOICE FILE
# ============================================================

invoice_rows = []

for order in orders:

    invoice_rows.append(
        {
            "invoice_id": order["invoice_id"],
            "order_id": order["order_id"],
            "amount": order["amount"],
            "gross_amount": order["amount"],
            "currency": "INR",
            "transaction_date": order["date"],
            "merchant_id": "merchant_demo",
            "customer": order["customer"],
            "narration": "Demo customer invoice",
        }
    )


invoice_df = pd.DataFrame(
    invoice_rows
)

invoice_file = (
    OUT / "01_demo_invoices.xlsx"
)

invoice_df.to_excel(
    invoice_file,
    index=False,
)


# ============================================================
# 2. RAZORPAY FILE
# ============================================================

razorpay_rows = []

for i, order in enumerate(
    orders,
    start=1,
):

    amount = order["amount"]

    # --------------------------------------------------------
    # Rows 1-6: exact
    # --------------------------------------------------------

    if i <= 6:

        fee = 0.0
        settlement_amount = amount

    # --------------------------------------------------------
    # Rows 7-8: MDR / fuzzy
    # --------------------------------------------------------

    elif i in (7, 8):

        fee = round(
            amount * 0.018,
            2,
        )

        settlement_amount = round(
            amount - fee,
            2,
        )

    # --------------------------------------------------------
    # Row 9: split payment
    # --------------------------------------------------------

    elif i == 9:

        fee = 0.0
        settlement_amount = amount

    # --------------------------------------------------------
    # Row 10: intentionally mismatched
    # --------------------------------------------------------

    elif i == 10:

        fee = 0.0

        settlement_amount = (
            amount - 1250
        )

    # --------------------------------------------------------
    # Row 11: ML review
    # --------------------------------------------------------

    elif i == 11:

        fee = 0.0

        settlement_amount = (
            amount - 875
        )

    # --------------------------------------------------------
    # Row 12: AI exception
    # --------------------------------------------------------

    else:

        fee = 0.0

        settlement_amount = (
            amount - 4200
        )

    razorpay_rows.append(
        {
            "Payment ID": f"PAY-DEMO-{i:03d}",
            "Order ID": order["order_id"],
            "Amount": amount,
            "Fee": fee,
            "Settlement Amount": settlement_amount,
            "Settlement ID": f"SET-DEMO-{i:03d}",
            "Currency": "INR",
            "Settlement Date": order["date"],
        }
    )


razorpay_df = pd.DataFrame(
    razorpay_rows
)

razorpay_file = (
    OUT
    / "02_demo_razorpay_settlements.xlsx"
)

razorpay_df.to_excel(
    razorpay_file,
    index=False,
)


# ============================================================
# 3. BANK FILE
# ============================================================

bank_rows = []

for i, order in enumerate(
    orders,
    start=1,
):

    amount = order["amount"]

    # --------------------------------------------------------
    # Rows 1-6: exact
    # --------------------------------------------------------

    if i <= 6:

        credit_amount = amount

        order_id = order["order_id"]

    # --------------------------------------------------------
    # Rows 7-8: MDR
    # --------------------------------------------------------

    elif i in (7, 8):

        fee = round(
            amount * 0.018,
            2,
        )

        credit_amount = round(
            amount - fee,
            2,
        )

        order_id = order["order_id"]

    # --------------------------------------------------------
    # Row 9: split payment
    #
    # The matching engine searches bank credits
    # in a 3-day window.
    # --------------------------------------------------------

    elif i == 9:

        credit_amount = amount / 2

        order_id = None

        bank_rows_part_1 = {
            "Transaction ID": "BANK-DEMO-009-A",
            "Order ID": None,
            "Credit": round(
                amount / 2,
                2,
            ),
            "Debit": None,
            "Currency": "INR",
            "Transaction Date": order["date"],
            "Narration": "Split payment part A",
        }

        bank_rows_part_2 = {
            "Transaction ID": "BANK-DEMO-009-B",
            "Order ID": None,
            "Credit": round(
                amount - round(amount / 2, 2),
                2,
            ),
            "Debit": None,
            "Currency": "INR",
            "Transaction Date": order["date"],
            "Narration": "Split payment part B",
        }

        bank_rows.append(
            bank_rows_part_1
        )

        bank_rows.append(
            bank_rows_part_2
        )

        continue

    # --------------------------------------------------------
    # Row 10: unresolved
    # --------------------------------------------------------

    elif i == 10:

        credit_amount = (
            amount - 2500
        )

        order_id = order["order_id"]

    # --------------------------------------------------------
    # Row 11: ML review
    # --------------------------------------------------------

    elif i == 11:

        credit_amount = (
            amount - 875
        )

        order_id = order["order_id"]

    # --------------------------------------------------------
    # Row 12: AI exception
    # --------------------------------------------------------

    else:

        credit_amount = (
            amount - 4200
        )

        order_id = order["order_id"]

    bank_rows.append(
        {
            "Transaction ID": f"BANK-DEMO-{i:03d}",
            "Order ID": order_id,
            "Credit": credit_amount,
            "Debit": None,
            "Currency": "INR",
            "Transaction Date": order["date"],
            "Narration": "Demo bank credit",
        }
    )


bank_df = pd.DataFrame(
    bank_rows
)

bank_file = (
    OUT / "03_demo_bank_statement.xlsx"
)

bank_df.to_excel(
    bank_file,
    index=False,
)


print()
print("Demo files created:")
print(invoice_file)
print(razorpay_file)
print(bank_file)
print()
print("Expected demo:")
print("  Exact        : 6")
print("  MDR/Fuzzy    : 2")
print("  Split        : 1")
print("  ML Review    : 1")
print("  AI Exception : 2")
