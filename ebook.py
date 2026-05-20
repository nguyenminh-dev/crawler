import os
import glob
import re
import asyncio
import random
from urllib.parse import urlparse
from playwright.async_api import async_playwright

BASE_URL = "https://sachmoi.net"
DOWNLOAD_DIR = r"D:\OneDrive\Ebook"
LINKS_DIR = "links_by_pages"
LOG_FILE = "downloaded_log.txt"  # File ghi nhớ những sách đã xử lý

# =========================================================
# CẤU HÌNH ĐA LUỒNG & CHỐNG CHẶN (ANTI RATE-LIMIT)
# =========================================================
MAX_CONCURRENT_TABS = 3  # Tab chạy cùng lúc
BOOKS_PER_BATCH = 15     # Tải xong 15 cuốn thì cho Bot nghỉ
REST_TIME = 60           # Nghỉ 60 giây trước khi tải đợt tiếp theo

STOP_CRAWLING = False 

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(LINKS_DIR, exist_ok=True)


# =========================================================
# HÀM XÓA POPUP (ASYNC)
# =========================================================
async def remove_popup(page):
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)
        await page.evaluate("""
            () => {
                const selectors = ['.modal', '.popup', '.overlay', '#overlay', '[role="dialog"]', '[class*="popup"]', '[class*="modal"]'];
                selectors.forEach(selector => {
                    document.querySelectorAll(selector).forEach(el => el.remove());
                });
                document.querySelectorAll('div').forEach(el => {
                    const style = window.getComputedStyle(el);
                    const zIndex = parseInt(style.zIndex || 0);
                    const isFixedOrAbs = style.position === 'fixed' || style.position === 'absolute';
                    if (isFixedOrAbs && zIndex > 999) { el.remove(); }
                });
                document.body.style.overflow = 'auto';
            }
        """)
    except Exception:
        pass


# =========================================================
# GIAI ĐOẠN 1.1: WORKER QUÉT 1 TRANG ĐỘC LẬP
# =========================================================
async def process_single_page(context, page_num, semaphore):
    global STOP_CRAWLING
    
    async with semaphore:
        if STOP_CRAWLING:
            return
            
        await asyncio.sleep(random.uniform(2.0, 5.0))
            
        page = await context.new_page()
        try:
            url = f"{BASE_URL}/trang/{page_num}/" if page_num > 1 else BASE_URL
            print(f"-> Đang quét Trang {page_num}...")
            
            response = await page.goto(url, wait_until="networkidle", timeout=60000)
            
            if response and response.status in [429, 403]:
                print(f"-> CẢNH BÁO: Bị Rate Limit ở Trang {page_num}. Nghỉ 15s...")
                await asyncio.sleep(15)
                return

            if response and response.status == 404:
                print(f"-> Trang {page_num} báo 404. Đã đến trang cuối! (Đang dừng hệ thống...)")
                STOP_CRAWLING = True
                return
                
            if page_num > 1 and (page.url == f"{BASE_URL}/" or page.url == BASE_URL):
                print(f"-> Trang {page_num} bị đẩy về trang chủ. (Đang dừng hệ thống...)")
                STOP_CRAWLING = True
                return

            await remove_popup(page)
            
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 1000);")
                await asyncio.sleep(0.5)
                
            links = await page.locator("a").evaluate_all("els => els.map(e => e.href)")
            blacklist = ["/danh-muc/", "/tac-gia/", "/trang/", "/page/", "/tag/", "/chinh-sach-bao-mat", "/dieu-khoan-su-dung", "/lien-he", "/img/", "#", "gsc.tab"]
            
            book_links_on_page = []
            for link in links:
                if not link.startswith(BASE_URL) or any(bw in link for bw in blacklist): continue
                path = urlparse(link).path
                if path in ["/", ""]: continue
                if path.strip("/").count("/") == 0: 
                    book_links_on_page.append(link)
            
            unique_links = sorted(list(set(book_links_on_page)))
            
            if not unique_links:
                print(f"-> Trang {page_num}: Không tìm thấy sách nào.")
            else:
                page_file_path = os.path.join(LINKS_DIR, f"page_{page_num}.txt")
                with open(page_file_path, "w", encoding="utf-8") as f:
                    for link in unique_links: f.write(link + "\n")
                print(f"-> THÀNH CÔNG: Đã lưu {len(unique_links)} sách ở Trang {page_num}.")
                
        except Exception as e:
            print(f"-> LỖI TẠI TRANG {page_num}: {e}")
        finally:
            await page.close()


# =========================================================
# GIAI ĐOẠN 1.2: QUẢN LÝ ĐA LUỒNG QUÉT LINK
# =========================================================
async def crawl_all_links(context, start_page=1, end_page=500):
    global STOP_CRAWLING
    STOP_CRAWLING = False 
    
    print(f"BẮT ĐẦU QUÉT LINK TỪ TRANG {start_page} ĐẾN {end_page} ĐA LUỒNG...")
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TABS)
    tasks = []
    
    for page_num in range(start_page, end_page + 1):
        tasks.append(process_single_page(context, page_num, semaphore))
        
    await asyncio.gather(*tasks)


# =========================================================
# HÀM LƯU LOG NHỮNG SÁCH ĐÃ TẢI
# =========================================================
def log_downloaded_book(book_url):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(book_url + "\n")


# =========================================================
# GIAI ĐOẠN 2.1: WORKER TẢI 1 CUỐN SÁCH ĐỘC LẬP
# =========================================================
async def process_single_book(context, book_url, idx, total, semaphore):
    async with semaphore:
        await asyncio.sleep(random.uniform(2.0, 5.0))
        page = await context.new_page()
        
        for attempt in range(2):
            try:
                print(f"[{idx}/{total}] Đang xử lý: {book_url}")
                path = urlparse(book_url).path
                download_url = book_url if path.startswith("/download") else f"{BASE_URL}/download{path}"

                response = await page.goto(download_url, wait_until="domcontentloaded", timeout=60000)
                
                if response and response.status in [429, 403]:
                    raise Exception("Bị Rate Limit")

                await asyncio.sleep(3)
                await remove_popup(page)
                
                buttons = await page.locator("a").all()
                epub_btn, azw3_btn, pdf_btn = None, None, None

                for btn in buttons:
                    try:
                        text = (await btn.inner_text()).strip().lower()
                        if "download" not in text: continue
                            
                        href = await btn.get_attribute("href")
                        if not href: continue
                        
                        is_epub = ".epub" in href.lower()
                        is_azw3 = ".azw3" in href.lower()
                        is_pdf = ".pdf" in href.lower()
                        
                        if not is_epub and not is_azw3 and not is_pdf:
                            ancestor = btn
                            for _ in range(4):
                                try:
                                    ancestor = ancestor.locator("xpath=..")
                                    ancestor_text = (await ancestor.inner_text()).lower()
                                    if ".epub" in ancestor_text and len(ancestor_text) < 200:
                                        is_epub = True; break
                                    elif ".azw3" in ancestor_text and len(ancestor_text) < 200:
                                        is_azw3 = True; break
                                    elif ".pdf" in ancestor_text and len(ancestor_text) < 200:
                                        is_pdf = True; break
                                except: break
                        
                        # Lưu nút tìm được
                        if is_epub and not epub_btn: epub_btn = btn
                        elif is_azw3 and not azw3_btn: azw3_btn = btn
                        elif is_pdf and not pdf_btn: pdf_btn = btn
                    except: pass

                # Ưu tiên: EPUB > AZW3 > PDF
                target_btn = epub_btn if epub_btn else (azw3_btn if azw3_btn else pdf_btn)
                target_type = "EPUB" if epub_btn else ("AZW3" if azw3_btn else ("PDF" if pdf_btn else None))

                if target_btn:
                    print(f"[{idx}/{total}] -> Phát hiện {target_type}. Đang tiến hành tải...")
                    await target_btn.scroll_into_view_if_needed()

                    async with page.expect_download(timeout=120000) as download_info:
                        await target_btn.click(force=True)

                    download = await download_info.value
                    raw_name = download.suggested_filename
                    safe_name = re.sub(r'[\\/*?:"<>|]', "_", raw_name)
                    
                    expected_ext = f".{target_type.lower()}"
                    if not safe_name.lower().endswith(expected_ext) and "." not in safe_name:
                        safe_name += expected_ext
                        
                    save_path = os.path.join(DOWNLOAD_DIR, safe_name)
                    await download.save_as(save_path)
                    print(f"[{idx}/{total}] -> ĐÃ TẢI XONG: {safe_name}")
                    
                    log_downloaded_book(book_url)
                else:
                    print(f"[{idx}/{total}] -> Không có EPUB/AZW3/PDF, bỏ qua.")
                    log_downloaded_book(book_url)
                
                break 
                
            except Exception as e:
                if attempt == 0:
                    print(f"[{idx}/{total}] -> LỖI: {e}. Thử lại sau 10s...")
                    await asyncio.sleep(10)
                else:
                    print(f"[{idx}/{total}] -> BỎ QUA DO LỖI: {e}")
            
        await page.close()


# =========================================================
# GIAI ĐOẠN 2.2: TẢI SÁCH THEO TỪNG TRANG & GHI NHỚ THÔNG MINH
# =========================================================
async def download_books(context, start_page=1, end_page=None, start_index=1):
    if end_page is None:
        end_page = start_page

    print(f"\n[TIẾN HÀNH TẢI SÁCH TỪ TRANG {start_page} ĐẾN {end_page}]")
    
    if not os.path.exists(LINKS_DIR):
        print("-> Lỗi: Thư mục chứa link trống. Vui lòng quét link trước!")
        return

    all_book_links = []
    
    for page_num in range(start_page, end_page + 1):
        file_path = os.path.join(LINKS_DIR, f"page_{page_num}.txt")
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                all_book_links.extend([line.strip() for line in f if line.strip()])
        else:
            print(f"-> Bỏ qua Trang {page_num}: Chưa có file link.")

    all_book_links = list(dict.fromkeys(all_book_links))
    
    if start_index > 1:
        print(f"-> Yêu cầu: Bỏ qua {start_index - 1} cuốn sách đầu tiên...")
        all_book_links = all_book_links[start_index - 1 :]

    downloaded_set = set()
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            downloaded_set = set(line.strip() for line in f if line.strip())
            
    if downloaded_set:
        print(f"-> Phát hiện Sổ tay: Có {len(downloaded_set)} cuốn đã được xử lý trước đó.")
        
    pending_links = [link for link in all_book_links if link not in downloaded_set]
    total_books = len(pending_links)
    
    if total_books == 0:
        print("-> Tuyệt vời! Tất cả các sách trong khoảng trang này đều đã được tải.")
        return

    print(f"-> Còn lại {total_books} cuốn cần tải.")
    print("BẮT ĐẦU TẢI ĐA LUỒNG...\n" + "="*60)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TABS)
    
    for i in range(0, total_books, BOOKS_PER_BATCH):
        batch_links = pending_links[i : i + BOOKS_PER_BATCH]
        tasks = []
        
        for local_idx, book_url in enumerate(batch_links):
            real_idx = i + local_idx + 1 
            tasks.append(process_single_book(context, book_url, real_idx, total_books, semaphore))
            
        await asyncio.gather(*tasks)
        
        if i + BOOKS_PER_BATCH < total_books:
            print("\n" + "="*60)
            print(f"🌟 ĐÃ TẢI XONG ĐỢT {i//BOOKS_PER_BATCH + 1} (Được {i + len(batch_links)} cuốn).")
            print(f"💤 BOT NGHỈ NGƠI {REST_TIME}s ĐỂ TRÁNH RATE LIMIT...")
            print("="*60 + "\n")
            
            for time_left in range(REST_TIME, 0, -10):
                print(f"... còn {time_left} giây nữa sẽ tiếp tục ...")
                sleep_duration = 10 if time_left >= 10 else time_left
                await asyncio.sleep(sleep_duration)


# =========================================================
# KHỞI CHẠY TOOL
# =========================================================
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)

        # ---------------------------------------------------------
        # [BƯỚC 1] Quét link
        # await crawl_all_links(context, start_page=1, end_page=464)
        # ---------------------------------------------------------

        # ---------------------------------------------------------
        # [BƯỚC 2] Tải sách THEO TRANG VÀ THEO INDEX
        await download_books(context, start_page=1, end_page=464, start_index=226)
        # ---------------------------------------------------------

        await browser.close()
    
    print("\nHOÀN THÀNH TOÀN BỘ CHƯƠNG TRÌNH!")

if __name__ == "__main__":
    asyncio.run(main())