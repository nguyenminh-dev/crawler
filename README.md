## 🚀 Hướng dẫn Cài đặt & Khởi chạy
**Python:** Phiên bản **3.9 trở lên** (Khuyến nghị **Python 3.10 hoặc 3.11**).
  *(Khi cài đặt Python trên Windows, nhớ tích chọn ô **`Add Python to PATH`**).*

Chỉ cần mở **Terminal** (macOS/Linux) hoặc **Command Prompt / PowerShell** (Windows) tại thư mục chứa file `ebook.py` và gõ lần lượt 3 lệnh sau:

**Bước 1: Cài đặt thư viện Playwright**
```bash
pip install playwright
```

**Bước 2: Tải trình duyệt giả lập (Chromium)**
```bash
playwright install chromium

```
**Bước 3: Chạy Tool*
```bash
python ebook.py
```