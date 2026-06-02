# วิเคราะห์เชิงลึกฟังก์ชัน `simulate_walk_forward` (Trading Simulation Engine)

**ไฟล์ต้นทาง**: `./run_backtest_example.py`
**เวอร์ชันล่าสุดอัปเกรด Phase 2: Advanced Exit Logic Execution**

---

## 1. หลักการออกแบบ สมมติฐานทางเทคนิค และเป้าหมายทางธุรกิจ

### เป้าหมายทางธุรกิจ (Business Objectives)
เพื่อจำลองผลลัพธ์การลงทุน (Profit & Loss) เสมือนจริงในอดีต โดยอาศัยสัญญาณคาดการณ์ล่วงหน้าจาก Machine Learning (Ensemble 60/40) ควบคู่กับการบริหารความเสี่ยงแบบ Market Structure-Based เป้าหมายสูงสุดคือการประเมินความสามารถในการทำกำไรของโมเดล พร้อมระบบรักษาผลกำไร (Unrealized Profit) ให้ไหลย้อนกลับน้อยที่สุดด้วย Priority Exit Logic

### สมมติฐานทางเทคนิค (Technical Assumptions)
- **Execution T+1 (แก้ปัญหา Lookahead Bias)**: ตัดสินใจอิงข้อมูลจนถึงแท่ง T-1 และทำธุรกรรมจริงที่ Open Price ของแท่ง T เสมอ
- **Single-Asset Single-Position**: ถือครองสูงสุดเพียง 1 ไม้ ไม่มีการถัวเฉลี่ย
- **Market Structure Validation**: สันนิษฐานว่าการหลุด Swing Low 15 นาทีล่าสุด, การหลุดเส้น VWAP, หรือปริมาณการซื้อขายที่สูงผิดปกติ (Volume Climax) คือจุดสิ้นสุดของแนวโน้มขาขึ้นในระดับ Intraday 

### หลักการออกแบบ (Design Principles)
- **Fixed Fraction Position Sizing**: จำนวนเงินที่ใช้ซื้อในแต่ละครั้งกำหนดไว้ที่ 20% ของกระแสเงินสดรวม (Capital)
- **Trade Constraint Logic**: จำกัดความถี่ในการเทรด ป้องกันการเทรดรัวเกินไป (Overtrading)
- **State Management**: บันทึกสถานะเชิงลึก ได้แก่ `highest_since_entry`, `was_above_vwap`, และ `max_unrealized_profit_pct` ตลอดระยะเวลาที่ถือครองสถานะ
- **Priority-Based Exit Logic**: การตั้งกฎจุดออกตามลำดับความสำคัญ 1 ถึง 6 (Prioritized Evaluation)

---

## 2. ขั้นตอนการทำงานและจุดตัดสินใจ (End-to-End Workflow)

1. **Initialization & Feature Computation**: 
   - กำหนดค่าจำกัดการเทรด (Limit Counters) 
   - คำนวณ Intraday VWAP และ `nearest_swing_low` (ค่าต่ำสุดใน 15 แท่งย้อนหลัง) เตรียมไว้สำหรับการเทียบเคียง (Structure Break)
2. **Chronological Loop (`itertuples`)**: วนลูปผ่านข้อมูลทีละแท่งเวลา
3. **Exit Evaluation (กรณีถือของอยู่)**: ระบบตรวจสอบเงื่อนไขการขายตามลำดับความสำคัญ (If-Elif Structure):
   - **Priority 1 (EOD Force Close)**: ปิดสถานะล้างพอร์ตตอน 15:55
   - **Update Market Tracking**: อัปเดต `highest_since_entry`, `was_above_vwap`, และ `max_unrealized_profit_pct`
   - **Priority 2 (VWAP Violation)**: หากเคยอยู่เหนือ VWAP แล้วร่วงทะลุต่ำกว่า VWAP 0.1% จะขายทิ้ง
   - **Priority 3 (Volume Climax)**: ถ้ามีกำไรและวอลลุ่มปูดแรงเกิน 3.5 เท่าของ SMA20 จะล็อกกำไรทันที
   - **Priority 4 (Swing Low Breakdown)**: หากร่วงหลุด `nearest_swing_low` จะสั่งปิดหนีเพื่อหยุดกำไรทิพย์
   - **Priority 5 (Smart ML Exit)**: ถ้าระบบ ML ประเมิน Prob < SELL_THRESHOLD และกำไรมากกว่า Minimum Profit ระบบจะสั่งขาย
   - **Priority 6 (Hard Stop Fallback)**: เป็นกำแพงป้องกันชั้นสุดท้าย ตัดชน SL หรือ TP ปกติ
   - **Limit Reached Evaluation**: อัปเดต Counter ขาดทุน/กำไร/รวม หากถึงขีดจำกัดจะบล็อคการซื้อเพิ่ม
4. **Entry Evaluation (กรณีพอร์ตว่าง และยังไม่ชน Limit)**:
   - เช็คว่า Prob > Dynamic Threshold หรือไม่
   - เข้าซื้อด้วย 20% ของเงินทุน พร้อมตั้งเป้า TP/SL อ้างอิงตาม ATR
5. **Equity Tracking**: บันทึกมูลค่าพอร์ตปัจจุบัน Mark-to-Market แบบเรียลไทม์

---

## 3. วิเคราะห์โค้ด Python แบบบรรทัดต่อบรรทัดและพารามิเตอร์

```python
def simulate_walk_forward(symbol: str, data: pd.DataFrame, versions: dict, initial_capital: float = 100000.0, tp_sl_mode: str = "FIXED", intraday_mode: bool = False, max_loss_trades: int = 3, max_win_trades: int = 3, max_total_trades: int = 5) -> MLBacktestResult:
```
**บทบาท**: ฟังก์ชันหลัก รับพารามิเตอร์เพิ่มเติมสำหรับควบคุม Trade Limits และ Intraday Constraint 

```python
    # Calculate Intraday VWAP
    data["typical_price"] = (data["high"] + data["low"] + data["close"]) / 3
    data["vwap"] = (data["typical_price"] * data["volume"]).groupby(data.index.date).cumsum() / data["volume"].groupby(data.index.date).cumsum()
    # Calculate nearest swing low
    data["nearest_swing_low"] = data["low"].rolling(window=15).min().shift(1)
```
**บทบาทเชิงเทคนิค**: เตรียมฟีเจอร์ Market Structure แบบ On-the-fly (สร้าง Vectorised columns) ให้พร้อมสำหรับการใช้ตัดสินใจ (Exit)

```python
                # 0. Update Max Price, Highest Since Entry, & VWAP status
                current_trade.highest_since_entry = max(current_trade.highest_since_entry, high_price)
                if not current_trade.was_above_vwap and (open_price > row.vwap or high_price > row.vwap):
                    current_trade.was_above_vwap = True
                
                unrealized_pnl = (current_trade.highest_since_entry - current_trade.entry_price) / current_trade.entry_price
                current_profit_pct = (open_price - current_trade.entry_price) / current_trade.entry_price
                current_trade.max_unrealized_profit_pct = max(current_trade.max_unrealized_profit_pct, current_profit_pct)
```
**บทบาทเชิงธุรกิจ**: การ State Management ตรวจจับค่าสูงสุดและอัปเดตสถิติเป้าหมายแบบเรียลไทม์ จำเป็นอย่างยิ่งเพื่อวัดความสำเร็จของ Trade แต่อย่างเดียว

```python
                # Evaluate Exits: Priority 2-6
                # Priority 2: VWAP Violation
                if current_trade.was_above_vwap and price < (row.vwap * 0.999):
                    exit_price = price
                    exit_reason = "VWAP Violation"
                # Priority 3: Volume Climax
                elif current_profit_pct > 0 and pd.notna(row.vol_sma_20) and row.vol_sma_20 > 0 and row.volume > (row.vol_sma_20 * 3.5):
                    exit_price = open_price
                    exit_reason = "Volume Climax"
```
**บทบาทเชิงกลยุทธ์**: อัลกอริทึมประเมินตาม Priority (If-Elif) เพื่อแก้ปัญหา Parabolic Reversal หุ้นที่ขึ้นแรงพร้อมวอลลุ่มมากผิดปกติจะโดนกฎ Priority 3 สกัดไว้ทำกำไรก่อน

```python
                # Priority 4: Swing Low Breakdown
                elif unrealized_pnl > 0.005 and pd.notna(row.nearest_swing_low) and low_price < row.nearest_swing_low:
                    exit_price = row.nearest_swing_low
                    if open_price < row.nearest_swing_low:
                        exit_price = open_price
                    exit_reason = "Structure Break"
```
**บทบาทเชิงกลยุทธ์**: ไม่รอให้ชน Stop Loss เดิมที่ลึกเกินไป อาศัยโครงสร้างราคาเป็นเครื่องพิสูจน์ หากโมเมนตัมเสีย (Structure Broken) ให้ตัดใจขายล็อกกำไรทันที

---

## 4. บริบทการเรียกใช้และ Dependencies

- **Context/Trigger**: เป็นหัวใจของ Backtester จะทำงานทุกครั้งที่มีการรันคำสั่ง `run_backtest_example.py`
- **Caller**: ถูกเรียกใช้โดย `process_symbol`
- **Dependencies ที่พึ่งพา**:
  - `TradeRecord` (อัปเกรดเพิ่ม `max_unrealized_profit_pct`, `highest_since_entry` และ `was_above_vwap`), `BacktestMetrics`, `MLBacktestResult` 
  - `calculate_metrics`: ฟังก์ชันคำนวณสถิติ
  - ต้องทำงานร่วมกับฟีเจอร์ที่ถูกทำ Vectorization เช่น `nearest_swing_low`

---

## 5. MLOps Best Practices และการปรับปรุงที่เกิดขึ้น

1. **Prioritized Logic Structure**: เปลี่ยนจากการรัน If อิสระมาใช้บล็อก `if-elif` ตามลำดับชั้น (Hierarchy of Needs) สิ่งที่สำคัญที่สุดอย่าง VWAP และ Volume Climax จะถูกประเมินก่อนเสมอ เพิ่มประสิทธิภาพ O(1) ของ `itertuples`
2. **Market Structure vs Fixed Targets**: เลิกอิงเป้าตายตัว (Fixed Take Profit) อาศัยโมเมนตัมตลาดและสัญญาณ ML ช่วยล็อกกำไรอย่างสมเหตุสมผล
3. **Hard Stop Fallback**: การคง SL/TP ไว้เป็น Priority สุดท้ายรับประกันว่าจะไม่เกิดหายนะเมื่อตลาดแกว่งเกินจุดที่ VWAP หรือ Swing Low จะรับมือได้
