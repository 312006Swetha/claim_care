import pandas as pd
import os

print("Script started...")

# ============================================================
# CHANGE THIS TO YOUR ACTUAL CSV FILE NAME
# ============================================================

input_file = "cms_csv/carrier.csv"

# ============================================================
# SETTINGS
# ============================================================

chunk_size = 1000
output_folder = "split_carrier"

os.makedirs(output_folder, exist_ok=True)

# ============================================================
# CHECK FILE
# ============================================================

if not os.path.exists(input_file):
    print(f"ERROR: File not found: {input_file}")
    print("\nFiles in current folder:")

    for file in os.listdir():
        print(" -", file)

    exit()

# ============================================================
# SPLIT CSV
# ============================================================

batch_number = 1
total_records = 0

for chunk in pd.read_csv(input_file, chunksize=chunk_size):

    output_file = os.path.join(
        output_folder,
        f"batch_{batch_number:03d}.csv"
    )

    chunk.to_csv(
        output_file,
        index=False
    )

    print(
        f"Created: {output_file} "
        f"--> {len(chunk)} records"
    )

    total_records += len(chunk)
    batch_number += 1

# ============================================================
# SUMMARY
# ============================================================

print("\n================================")
print("SPLITTING COMPLETED")
print("================================")

print("Total records:", total_records)
print("Total batches:", batch_number - 1)
print("Output folder:", output_folder)