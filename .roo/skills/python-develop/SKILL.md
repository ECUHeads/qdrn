---
name: python-develop
description: design and developing python
---

# Python Develop

## Instructions

# 🚨 CRITICAL DIRECTIVE: Python Development & Modification Protocol
**PENALTY RATE: MAXIMUM.** You are operating under a strict 128K Context Window constraint on a Local LLM (MTP enabled). You MUST execute the following workflow systematically. Failure to adhere to Security, Architecture, Unit Testing, or Context rules constitutes a failed generation.

## 1. Codebase Discovery via Vector Index (MANDATORY FIRST STEP)
- **Search Before Write:** ก่อนเริ่มวางแผนหรือเขียนโค้ดใหม่ **ต้อง** ใช้ Codebase Vector Index ของ Roo Code เพื่อค้นหาโครงสร้างที่มีอยู่แล้ว (Existing Classes, Base Classes, Utility functions) เสมอ
- **Prevent Duplication:** ห้ามสร้างคลาสหรือฟังก์ชันใหม่หากมีสิ่งที่ทำงานเหมือนกันอยู่แล้วในระบบ ให้นำของเดิมมาใช้หรือทำการสืบทอด (Inherit) แทน

## 2. Architecture & Code Style Standards
- **Class-Based OOP:** โครงสร้างโค้ดหลักต้องเป็น Object-Oriented Programming (OOP) เสมอ ออกแบบโดยใช้ Base Class และการสืบทอด (Inheritance) ที่สมเหตุสมผล หลีกเลี่ยงการเขียนสคริปต์แบบลอยๆ
- **PEP-8 Compliance:** ปฏิบัติตามมาตรฐาน PEP-8 อย่างเคร่งครัด (Naming conventions, spacing, type hinting)
- **Predictable MTP Formatting:** แยกตรรกะการคิด (Plan) ออกจากการเขียน (Code) อย่างชัดเจน เพื่อให้ MTP สร้างโครงสร้าง Class ได้อย่างรวดเร็ว

## 3. Strict Security & PDPA Compliance (CRITICAL)
- **PDPA / Privacy:** โค้ดที่จัดการกับข้อมูลผู้ใช้งาน (PII) ต้องมีการทำ Data Masking หรือ Anonymization เสมอ **ห้าม** Print, Log, หรือบันทึกข้อมูลส่วนบุคคลลงระบบโดยไม่เข้ารหัสเด็ดขาด
- **Authentication (JWT):** ทุก Endpoint หรือฟังก์ชันที่ต้องการความปลอดภัย ต้องมีการตรวจสอบ JWT (JSON Web Token) Validation เสมอ (เช็ค Expiration, Signature, และ Role claims)
- **Security Standards:** ปฏิบัติตามมาตรฐานความปลอดภัยระดับสากล (เช่น OWASP Top 10) ป้องกัน SQL Injection และทำ Input Validation ทุกครั้งก่อนนำข้อมูลไปประมวลผล

## 4. Aggressive Filtering & Context Blueprint
- กำหนด Prerequisites เสมอ
- **[STRICT]** ตรวจสอบและอัปเดตไฟล์ `.rooignore` ก่อนเริ่มงานทุกครั้ง บล็อกโฟลเดอร์ที่ไม่จำเป็นทั้งหมด เพื่อรักษาพื้นที่ 128K Context 

## 5. Action Plan & Test-Driven Checkpoints
- สร้าง Action Plan (ภายใต้หัวข้อ `### PLAN`) ระบุลำดับขั้นตอนอย่างชัดเจน
- **[MANDATORY]** ทุกๆ Checkpoint ใน Action Plan **ต้องระบุรายละเอียดของ Unit Test** (เช่น ชื่อไฟล์ `tests/test_*.py` และพฤติกรรมที่จะทดสอบ) ควบคู่ไปด้วยเสมอ
- ทุกขั้นตอนต้องสามารถรันทดสอบแยกกันได้ (Standalone Testable) หากขั้นตอนใดไม่สามารถทดสอบเดี่ยวๆ ได้ ให้ทำการยุบรวม (Combine) กับขั้นตอนอื่นทันทีจนกว่าจะสามารถเขียน Unit Test ครอบคลุมได้ โดยไม่ทำให้โค้ดส่วนอื่นเสียหาย

## 6. Targeted Execution & Test Running (MTP Optimized)
- ดำเนินการเขียนโค้ดและแก้ไขตรรกะภายใต้หัวข้อ `### CODE`
- **[CRITICAL]** เมื่อเสร็จสิ้นโค้ดในแต่ละ Checkpoint **ต้องเขียนหรืออัปเดตไฟล์ Unit Test ทันที** จากนั้นให้รันคำสั่งทดสอบจริง (เช่น `pytest` หรือ `python -m unittest`) ผ่าน Environment ก่อนจะก้าวไปทำขั้นตอนถัดไป ห้ามปล่อยผ่านโดยเด็ดขาด

## 7. Progress & Test Results Reporting (Structured Output)
- หลังจากรันทดสอบในแต่ละขั้นตอนเสร็จสิ้น ให้รายงานความคืบหน้าพร้อม **Test Results Log** โดยใช้โครงสร้างที่ตรงตาม Action Plan อย่างเคร่งครัด ดังนี้:

```

### [PASS/FAIL] Step X: [ชื่อขั้นตอนตาม Action Plan]

* **Target Code**: `path/to/module.py`
* **Test File**: `tests/test_module.py`
* **Execution Command**: `pytest tests/test_module.py::test_case_name`
* **Test Result Summary**: [เช่น 3 passed, 0 failed, 0.05s]
* **Verification**: [สรุปสั้นๆ ว่าผลลัพธ์ตรงตามพฤติกรรมที่คาดหวังอย่างไร]

```

## 8. Proactive Clarification & Options
- หากพบความเสี่ยงที่จะกระทบระบบเดิม หรือไม่แน่ใจ ให้หยุดและสอบถามทันที
- เสนอ "ทางเลือก" พร้อม Trade-offs เสมอ หากมี Design pattern หรือ Security approach มากกว่า 1 วิธี

## 9. STRICT 128K Context Management (STATE HANDOFF)
- ประเมิน Context เสมอ เมื่อใช้งาน Token ใกล้จุดวิกฤต (ประมาณ 80,000 Tokens) ให้หยุดการทำงาน
- สร้างไฟล์ `STATE_SUMMARY.md` สรุปสถานะปัจจุบัน (สิ่งที่ทำเสร็จ, Test Results ล่าสุด, Class ที่สืบทอด, และ Action Plan ที่เหลือ) 
- แจ้งให้ผู้ใช้ "Clear Context" และใช้ `STATE_SUMMARY.md` ในการ Resume การทำงานใน Session ใหม่

## 10. External Connections & API
- หากมีการเชื่อมต่อ API ให้สอบถาม Parameters ที่จำเป็นเสมอ ห้าม Mock data เองเว้นแต่ได้รับคำสั่งอย่างชัดเจน
- ตรวจสอบให้แน่ใจว่า API Calls มีการจัดการ Error Handling และ Timeout อย่างเหมาะสมเสมอ  
