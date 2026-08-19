import sqlite3
import pandas as pd
from sqlalchemy import create_engine

# ============================================================
# SQLITE
# ============================================================

SQLITE_DB = r"C:/Users/sweth/OneDrive/Pictures/Desktop/Congnizant/claim_sentinel.db"

# ============================================================
# MYSQL
# ============================================================

MYSQL_USER = "root"
MYSQL_PASSWORD = "Shwe16"
MYSQL_HOST = "127.0.0.1"
MYSQL_PORT = 3306
MYSQL_DATABASE = "claim_sentinel"

# ============================================================
# TABLES
# ============================================================

tables = [
    "pharmacy_dlsum_batch_001",
    "pharmacy_hlsum_batch_001"
]

# ============================================================
# CONNECTIONS
# ============================================================

sqlite_conn = sqlite3.connect(SQLITE_DB)

mysql_engine = create_engine(
    f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
    f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
)

# ============================================================
# COPY TABLES
# ============================================================

for table in tables:

    print("\n====================================")
    print("Processing:", table)
    print("====================================")

    # Read SQLite table
    df = pd.read_sql_query(
        f'SELECT * FROM "{table}"',
        sqlite_conn
    )

    print("Rows found:", len(df))
    print("Columns found:", len(df.columns))

    print("\nOriginal columns:")
    print(df.columns.tolist())

    # --------------------------------------------------------
    # RENAME COLUMNS
    # --------------------------------------------------------

    new_columns = []

    for i, column in enumerate(df.columns):

        column = str(column).strip()

        # MySQL identifier limit = 64 characters
        if len(column) > 64:
            column = f"column_{i + 1}"

        # Remove problematic characters
        column = (
            column
            .replace(" ", "_")
            .replace(",", "")
            .replace("-", "_")
            .replace("/", "_")
            .replace("(", "")
            .replace(")", "")
        )

        new_columns.append(column)

    df.columns = new_columns

    print("\nNew columns:")
    print(df.columns.tolist())

    # --------------------------------------------------------
    # WRITE TO MYSQL
    # --------------------------------------------------------

    df.to_sql(
        name=table,
        con=mysql_engine,
        if_exists="replace",
        index=False,
        chunksize=5000
    )

    print("\nSuccessfully copied:", table)

# ============================================================
# CLOSE
# ============================================================

sqlite_conn.close()

print("\n====================================")
print("ALL TABLES COPIED SUCCESSFULLY")
print("====================================")