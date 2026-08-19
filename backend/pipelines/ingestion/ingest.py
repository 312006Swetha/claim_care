import sqlite3
import mysql.connector
from mysql.connector import Error

# ============================================================
# CONFIGURATION
# ============================================================

SQLITE_DB = r"claim_sentinel.db"

MYSQL_HOST = "localhost"
MYSQL_USER = "root"
MYSQL_PASSWORD = "Shwe16"

MYSQL_DATABASE = "claim_sentinel"

BATCH_SIZE = 500


# ============================================================
# SQLITE TYPE -> MYSQL TYPE
# ============================================================

def sqlite_to_mysql_type(sqlite_type):
    t = (sqlite_type or "").upper()

    if "INT" in t:
        return "BIGINT"

    if "CHAR" in t or "CLOB" in t or "TEXT" in t:
        return "TEXT"

    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return "DOUBLE"

    if "DECIMAL" in t or "NUMERIC" in t:
        return "DECIMAL(18,4)"

    if "BLOB" in t:
        return "LONGBLOB"

    if "DATE" in t or "TIME" in t:
        return "DATETIME"

    return "TEXT"


# ============================================================
# CONNECT SQLITE
# ============================================================

print("=" * 70)
print("SQLITE → MYSQL DATABASE COPY")
print("=" * 70)

sqlite_conn = sqlite3.connect(SQLITE_DB)
sqlite_cursor = sqlite_conn.cursor()

print("\nSQLite database:")
print(SQLITE_DB)


# ============================================================
# GET TABLES
# ============================================================

sqlite_cursor.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
      AND name NOT LIKE 'sqlite_%'
    ORDER BY name
""")

tables = [row[0] for row in sqlite_cursor.fetchall()]

print("\nTables found:", len(tables))

for table in tables:
    print("  -", table)


# ============================================================
# CONNECT MYSQL
# ============================================================

try:

    mysql_conn = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD
    )

    mysql_cursor = mysql_conn.cursor()

    print("\nConnected to MySQL.")


    # ========================================================
    # CREATE DATABASE
    # ========================================================

    mysql_cursor.execute(
        f"""
        CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}`
        CHARACTER SET utf8mb4
        COLLATE utf8mb4_unicode_ci
        """
    )

    mysql_cursor.execute(
        f"USE `{MYSQL_DATABASE}`"
    )

    print(f"MySQL database: {MYSQL_DATABASE}")


    # ========================================================
    # COPY EACH TABLE
    # ========================================================

    for table in tables:

        print("\n" + "-" * 70)
        print(f"TABLE: {table}")
        print("-" * 70)


        # ----------------------------------------------------
        # Get SQLite schema
        # ----------------------------------------------------

        sqlite_cursor.execute(
            f'PRAGMA table_info("{table}")'
        )

        columns = sqlite_cursor.fetchall()

        if not columns:
            continue


        column_names = [
            column[1]
            for column in columns
        ]


        # ----------------------------------------------------
        # Drop existing MySQL table
        # ----------------------------------------------------

        mysql_cursor.execute(
            f"DROP TABLE IF EXISTS `{table}`"
        )


        # ----------------------------------------------------
        # Create MySQL table
        # ----------------------------------------------------

        definitions = []

        for column in columns:

            cid = column[0]
            name = column[1]
            sqlite_type = column[2]
            not_null = column[3]
            default_value = column[4]
            primary_key = column[5]

            mysql_type = sqlite_to_mysql_type(sqlite_type)

            definition = f"`{name}` {mysql_type}"

            if primary_key:
                definition += " PRIMARY KEY"

            if not_null:
                definition += " NOT NULL"

            definitions.append(definition)


        create_sql = f"""
        CREATE TABLE `{table}` (
            {", ".join(definitions)}
        ) ENGINE=InnoDB
        """

        mysql_cursor.execute(create_sql)

        print(
            f"Created table with {len(columns)} columns."
        )


        # ----------------------------------------------------
        # Read SQLite data
        # ----------------------------------------------------

        sqlite_cursor.execute(
            f'SELECT * FROM "{table}"'
        )

        rows_inserted = 0


        # ----------------------------------------------------
        # Insert data in batches
        # ----------------------------------------------------

        placeholders = ", ".join(
            ["%s"] * len(column_names)
        )

        columns_sql = ", ".join(
            f"`{col}`"
            for col in column_names
        )

        insert_sql = f"""
        INSERT INTO `{table}`
        ({columns_sql})
        VALUES ({placeholders})
        """

        while True:

            rows = sqlite_cursor.fetchmany(BATCH_SIZE)

            if not rows:
                break

            try:

                mysql_cursor.executemany(
                    insert_sql,
                    rows
                )

                mysql_conn.commit()

                rows_inserted += len(rows)

                print(
                    f"Inserted: {rows_inserted:,} rows",
                    end="\r"
                )

            except Exception as e:

                print(
                    f"\nError inserting into {table}: {e}"
                )

                mysql_conn.rollback()

                raise


        print(
            f"\nCompleted: {rows_inserted:,} rows"
        )


    # ========================================================
    # FINAL RESULT
    # ========================================================

    print("\n" + "=" * 70)
    print("COPY COMPLETED SUCCESSFULLY")
    print("=" * 70)

    print(f"""
SQLite:
    claim_sentinel.db
    ✓ Original database preserved

MySQL:
    claim_sentinel
    ✓ All tables created
    ✓ All records copied

Batch size:
    {BATCH_SIZE}
""")


except Error as e:

    print("\nMYSQL ERROR:")
    print(e)


finally:

    if 'mysql_cursor' in locals():
        mysql_cursor.close()

    if 'mysql_conn' in locals() and mysql_conn.is_connected():
        mysql_conn.close()

    sqlite_cursor.close()
    sqlite_conn.close()

    print("\nConnections closed.")