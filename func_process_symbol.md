# วิเคราะห์เชิงลึกฟังก์ชัน `process_symbol` (ML Backtest Orchestrator)

**ไฟล์ต้นทาง**: `./run_backtest_example.py`
**เวอร์ชันล่าสุดอัปเกรด Phase 2: Model Integration & Execution**

---

## 1. หลักการออกแบบ สมมติฐานทางเทคนิค และเป้าหมายทางธุรกิจ

### เป้าหมายทางธุรกิจ (Business Objectives)
เป้าหมายหลักคือการทำให้กระบวนการทดสอบกลยุทธ์ย้อนหลัง (Backtesting) ด้วยระบบ Machine Learning เป็นไปอย่างอัตโนมัติ รวดเร็ว และเป็นมาตรฐาน ฟังก์ชันนี้เปรียบเสมือนโรงงานผลิตรายงานประเมินผล ที่รับชื่อหุ้นและช่วงเวลาเข้ามา แล้วขับเคลื่อนระบบให้คืนผลลัพธ์เป็นชิ้นงานที่พร้อมใช้งานสำหรับนักวิเคราะห์ (กราฟ, Trade Log, Metrics) ทันที เพื่อนำไปประกอบการตัดสินใจใช้งานโมเดลจริง

### สมมติฐานทางเทคนิค (Technical Assumptions)
- **Independency of Assets**: สมมติฐานว่าการเคลื่อนไหวและการประมวลผลของหุ้นแต่ละตัว (Symbol) เป็นอิสระต่อกัน (Cross-sectional Independence in processing) จึงสามารถรันแบบขนานใน Process แยกกัน (Multiprocessing) ได้อย่างปลอดภัย
- **Deterministic Outcomes**: การทดสอบต้องสามารถทำซ้ำได้ (Reproducibility) การรันด้วยพารามิเตอร์ชุดเดิมต้องให้ผลเหมือนเดิมทุกครั้ง
- **Component Modularity**: การแยกการทำงานเป็น Pipeline (Load -> Simulate -> Report) จะช่วยให้การดูแลรักษาง่ายขึ้น

### หลักการออกแบบ (Design Principles)
- **Orchestrator Pattern**: `process_symbol` ทำหน้าที่เป็นผู้ประสานงาน ไม่ได้เขียนตรรกะการเทรดหรือคณิตศาสตร์ไว้ในตัวมันเอง แต่ทำหน้าที่เรียก `load_ml_signals`, `simulate_walk_forward`, และ `generate_markdown_report` ตามลำดับ
- **Fail-Safe Processing**: ห่อหุ้มบล็อกหลักด้วย `try-except` เพื่อไม่ให้ความล้มเหลวของการทดสอบหุ้นตัวเดียวไปขัดจังหวะการทำงานของหุ้นตัวอื่นๆ ใน Thread/Process pool

---

## 2. ขั้นตอนการทำงานและจุดตัดสินใจ (End-to-End Workflow)

ลำดับการทำงานจากต้นน้ำถึงปลายน้ำ:
1. **Context Initialization**: ฟังก์ชันตั้งค่า seed เริ่มต้นสำหรับกระบวนการย่อย (`np.random.seed(42)`)
2. **Signal Generation (`load_ml_signals`)**: รวบรวมข้อมูลราคา คำนวณฟีเจอร์เทคนิคอล/มหภาค และเรียกโหลดโมเดลแบบ Offline Mode (โหมดนี้ห้ามรันการเทรนใหม่เด็ดขาดตามนโยบาย Strict ML)
3. **Walk-Forward Simulation (`simulate_walk_forward`)**: นำสัญญาณที่ได้มาเดินจำลองการเทรดทีละแท่งเทียน ผนวกเข้ากับการจัดการความเสี่ยงด้วย Priority Exit Logic 6 ระดับ (EOD Close, VWAP Violation, Volume Climax, Structure Break, ML Exit, SL/TP)
4. **Artifacts Creation (`plot_ml_backtest` & `generate_markdown_report`)**: นำวัตถุดิบ (Trades log) มาสร้างเป็นชิ้นงานรูปภาพและการรายงาน โดยคำนวณ **Exit Distribution** ชี้แจงเหตุผลการปิดออเดอร์ตาม Exit Priority ทั้งหมดลงในไฟล์ Markdown
5. **Data Aggregation**: ดึงค่า Metrics ที่สำคัญออกมาคำนวณสรุปและส่งคืนกลับไปเป็นพจนานุกรม (Dictionary)

---

## 3. วิเคราะห์โค้ด Python แบบบรรทัดต่อบรรทัด

```python
def process_symbol(symbol: str, start_date: str, end_date: str, model_choice: str, capital: float, tp_sl_mode: str, strict_ml: bool = True, intraday_mode: bool = False, max_loss_trades: int = 3, max_win_trades: int = 3, max_total_trades: int = 5):
```
**บทบาท**: กำหนด API สำหรับ Orchestrator โดยรับค่าพารามิเตอร์ที่จำเป็นทั้งหมด รวมถึงปัจจัยสลับโหมดและจำกัดการเทรด สังเกตว่า `strict_ml` ได้รับการกำหนดค่า Default เป็น `True` เพื่อความปลอดภัยตามมาตรฐาน MLOps

```python
    try:
        np.random.seed(42) # Reproducibility per process
```
**บทบาท**: ล็อคสถานะความสุ่ม เนื่องจาก Python `multiprocessing` อาจทำให้ subprocess เกิด state ที่ไม่สามารถควบคุมได้ ป้องกันผลลัพธ์การ Predict แกว่งจากการสุ่ม

```python
        data, versions = load_ml_signals(symbol, start_date, end_date, model_choice, strict_ml)
```
**บทบาท**: เป็นจุดที่กินพลังประมวลผลสูงสุด (Computation Bottleneck) โหลดและแปลงข้อมูล ไปจนถึงประเมินผลผ่าน ML Offline Load

```python
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
        os.makedirs(output_dir, exist_ok=True)
```
**บทบาท**: จัดการโครงสร้างไฟล์ ตรวจสอบและสร้างโฟลเดอร์ปลายทาง แฟล็ก `exist_ok=True` จะป้องกัน Race Condition ระหว่าง Process

```python
        res = simulate_walk_forward(symbol, data, versions, capital, tp_sl_mode, intraday_mode, max_loss_trades, max_win_trades, max_total_trades)
```
**บทบาท**: Core Trading Engine นำข้อมูลที่มีฟีเจอร์และ Signal ครบถ้วนมาทำ Walk-forward testing ตรวจสอบ Priority Exit Logic และได้รับ `res` กลับมาเป็น Data Class `MLBacktestResult`

```python
        chart_path = plot_ml_backtest(res, output_dir)
        report_path, company_name, sector = generate_markdown_report(res, output_dir, chart_path)
```
**บทบาท**: สร้างกราฟและรายงาน `generate_markdown_report` จะทำการดึงข้อมูล Trade log มาคำนวณทำตาราง **Exit Distribution** โดยอัตโนมัติ เพื่อให้ผู้ใช้มองเห็นสัดส่วนการล็อกกำไรด้วย VWAP/Volume Climax เทียบกับการโดนคัตลอส

```python
        # Calculate averages for summary
        avg_confidence = np.mean([t.confidence for t in res.trades]) if res.trades else 0.0
        avg_threshold = data["dynamic_threshold"].mean() if "dynamic_threshold" in data.columns else 0.50
```
**บทบาท**: ดึงตัวชี้วัดเชิงลึกของ ML ออกมา เป็นความเชื่อมั่นโดยเฉลี่ยและระดับเกณฑ์ความเสี่ยง เพื่อสะท้อนความสามารถเชิงสถิติของโมเดลต่อหุ้นตัวนั้นๆ

```python
        logger.info(f"✅ [{symbol}] สำเร็จ: Return={res.metrics.total_return:.2%} | Report: {report_path}")
        return {
            "symbol": symbol, ...
            "status": "ผ่านเกณฑ์" if res.metrics.total_return > 0 else "ไม่ผ่านเกณฑ์"
        }
```
**บทบาท**: ส่งผลตอบรับออกไปยัง Log Terminal ทันทีที่ทำเสร็จ และทำการ Normalize ผลลัพธ์เป็น Dictionary เพื่อให้ Main process นำไปทำเป็น DataFrame สรุปงบดุล

```python
    except Exception as e:
        logger.error(f"❌ [{symbol}] ผิดพลาด: {e}", exc_info=True)
        return None
```
**บทบาท**: ดักจับข้อผิดพลาดทั้งหมด ป้องกันไม่ให้ Subprocess ล่ม และส่งต่อ Stack Trace ก่อนรันคืนค่า `None` ไปให้ Main process ข้ามทิ้งไป

---

## 4. บริบทการเรียกใช้และ Dependencies

- **Caller**: ถูกเรียกใช้โดยฟังก์ชัน `main()` ในไฟล์ `./run_backtest_example.py` 
- **กลไกการกระตุ้น (Triggering Mechanism)**: เกิดขึ้นเมื่อรันสคริปต์ผ่าน Terminal โดยใช้ `concurrent.futures.ProcessPoolExecutor` สร้าง Subprocess ขนานกันตามจำนวนรายชื่อหุ้น
- **Dependencies ที่พึ่งพา**:
  - `load_ml_signals`
  - `simulate_walk_forward`
  - `generate_markdown_report`
  - `plot_ml_backtest`
