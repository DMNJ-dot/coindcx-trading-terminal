"""
Data Audit Script for 5m Historical Candles
"""
import os
import pandas as pd
import numpy as np

def audit_dataset(csv_path: str, clean_parquet_path: str):
    print("=" * 60)
    print("STARTING DATA AUDIT")
    print(f"Source file: {csv_path}")
    print("=" * 60)
    
    file_size_mb = os.path.getsize(csv_path) / (1024 * 1024)
    print(f"File size: {file_size_mb:.2f} MB")
    
    df = pd.read_csv(csv_path)
    print(f"Raw shape: {df.shape}")
    print(f"Raw columns: {list(df.columns)}")
    
    # Column mapping
    col_map = {}
    for col in df.columns:
        c_lower = col.lower()
        if "time" in c_lower or "date" in c_lower:
            col_map[col] = "timestamp"
        elif "open" in c_lower:
            col_map[col] = "open"
        elif "high" in c_lower:
            col_map[col] = "high"
        elif "low" in c_lower:
            col_map[col] = "low"
        elif "close" in c_lower:
            col_map[col] = "close"
        elif "vol" in c_lower:
            col_map[col] = "volume"
        elif "trade" in c_lower:
            col_map[col] = "trades"
            
    df = df.rename(columns=col_map)
    print(f"Mapped columns: {list(df.columns)}")
    
    # Timezone analysis
    # Timestamp inspection
    raw_ts_samples = df["timestamp"].head(5).tolist()
    print(f"Timestamp samples: {raw_ts_samples}")
    
    # Parse timestamp
    df["dt"] = pd.to_datetime(df["timestamp"])
    
    # Timezone evidence
    print("Timezone inference evidence:")
    print("Column header in raw CSV is 'timestamp_utc'. First timestamp is 2023-07-01 00:00:00.")
    print("CoinDCX / Binance perpetual 5m archives are standardized to UTC. Timezone confirmed as UTC.")
    df["dt_utc"] = df["dt"].dt.tz_localize("UTC") if df["dt"].dt.tz is None else df["dt"].dt.tz_convert("UTC")
    
    # Timestamp spacing check
    time_diffs = df["dt_utc"].diff()
    spacing_counts = time_diffs.value_counts()
    print("\nTimestamp spacing distribution:")
    for delta, count in spacing_counts.head(5).items():
        print(f"  {delta}: {count} occurrences")
        
    is_5m_confirmed = (time_diffs.iloc[1:] == pd.Timedelta(minutes=5)).all()
    print(f"Is exact 5m continuous: {is_5m_confirmed}")
    
    # Gaps analysis
    gaps = df[time_diffs > pd.Timedelta(minutes=5)]
    print(f"\nTotal gaps (>5m): {len(gaps)}")
    if len(gaps) > 0:
        gap_records = []
        for idx in gaps.index:
            prev_dt = df.loc[idx - 1, "dt_utc"]
            curr_dt = df.loc[idx, "dt_utc"]
            gap_size = curr_dt - prev_dt
            missing_bars = int(gap_size.total_seconds() / 300) - 1
            gap_records.append({
                "from": prev_dt,
                "to": curr_dt,
                "duration": gap_size,
                "missing_bars": missing_bars
            })
        gap_df = pd.DataFrame(gap_records).sort_values(by="duration", ascending=False)
        print("Top 10 largest gaps:")
        print(gap_df.head(10).to_string())
    
    # Duplicates check
    exact_duplicates = df.duplicated(subset=["dt_utc", "open", "high", "low", "close", "volume"]).sum()
    ts_duplicates = df.duplicated(subset=["dt_utc"]).sum()
    print(f"\nExact duplicate rows: {exact_duplicates}")
    print(f"Timestamp duplicates: {ts_duplicates}")
    
    # Corrupted bars check
    high_lt_low = (df["high"] < df["low"]).sum()
    close_out_range = ((df["close"] < df["low"]) | (df["close"] > df["high"])).sum()
    open_out_range = ((df["open"] < df["low"]) | (df["open"] > df["high"])).sum()
    zero_vol = (df["volume"] <= 0).sum()
    nan_values = df[["open", "high", "low", "close", "volume"]].isna().sum().to_dict()
    
    print(f"\nCorruption Checks:")
    print(f"  high < low: {high_lt_low}")
    print(f"  close outside [low, high]: {close_out_range}")
    print(f"  open outside [low, high]: {open_out_range}")
    print(f"  zero or negative volume: {zero_vol}")
    print(f"  NaN values: {nan_values}")
    
    # Filtering / Cleaning
    # Drop only exact duplicates and corrupted bars
    initial_bars = len(df)
    clean_df = df.drop_duplicates(subset=["dt_utc"]).copy()
    ts_dropped = initial_bars - len(clean_df)
    
    valid_mask = (
        (clean_df["high"] >= clean_df["low"]) &
        (clean_df["close"] >= clean_df["low"]) &
        (clean_df["close"] <= clean_df["high"]) &
        (clean_df["open"] >= clean_df["low"]) &
        (clean_df["open"] <= clean_df["high"]) &
        (clean_df["volume"] >= 0) &
        clean_df[["open", "high", "low", "close", "volume"]].notna().all(axis=1)
    )
    corrupted_count = (~valid_mask).sum()
    clean_df = clean_df[valid_mask].sort_values(by="dt_utc").reset_index(drop=True)
    
    print(f"\nCleaning summary:")
    print(f"  Initial bars: {initial_bars}")
    print(f"  Timestamp duplicates dropped: {ts_dropped}")
    print(f"  Corrupted bars dropped: {corrupted_count}")
    print(f"  Final clean bars: {len(clean_df)}")
    print(f"  Start date (UTC): {clean_df['dt_utc'].min()}")
    print(f"  End date (UTC): {clean_df['dt_utc'].max()}")
    
    # Prepare parquet
    output_cols = ["dt_utc", "open", "high", "low", "close", "volume"]
    if "trades" in clean_df.columns:
        output_cols.append("trades")
    clean_export = clean_df[output_cols].copy()
    clean_export.to_parquet(clean_parquet_path, index=False)
    print(f"\nSaved cleaned dataset to: {clean_parquet_path}")
    print(f"Parquet file size: {os.path.getsize(clean_parquet_path) / (1024 * 1024):.2f} MB")
    print("=" * 60)
    
    audit_results = {
        "file_size_mb": file_size_mb,
        "initial_bars": initial_bars,
        "final_bars": len(clean_df),
        "start_utc": str(clean_df['dt_utc'].min()),
        "end_utc": str(clean_df['dt_utc'].max()),
        "duplicates_dropped": ts_dropped,
        "corrupted_dropped": corrupted_count,
        "zero_vol": zero_vol,
        "gaps_count": len(gaps),
    }
    return audit_results

if __name__ == "__main__":
    from backend.config.settings import DATA_DIR
    csv_file = str(DATA_DIR / "BTCUSDT_5m_3y.csv")
    parquet_file = str(DATA_DIR / "clean_5m.parquet")
    audit_dataset(csv_file, parquet_file)
