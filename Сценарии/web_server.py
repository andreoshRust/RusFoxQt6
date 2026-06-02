# web_server.py - Полная версия со всеми функциями и менеджером заданий
import sys
import json
import traceback
import threading
import time
import uuid
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import uno
from com.sun.star.beans import PropertyValue

# ==================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ====================
uno_context = None
uno_desktop = None
job_manager = None

# ==================== МЕНЕДЖЕР ЗАДАНИЙ ====================

class Job:
    """Класс для хранения информации о задании"""
    def __init__(self, job_id, doc, file_path=None, is_temp=False):
        self.job_id = job_id
        self.doc = doc
        self.file_path = file_path
        self.is_temp = is_temp
        self.created_at = time.time()
        self.last_activity = time.time()
        self.lock = threading.Lock()
    
    def update_activity(self):
        """Обновить время последней активности"""
        self.last_activity = time.time()
    
    def is_expired(self, timeout_seconds=60):
        """Проверить, истекло ли время задания"""
        return (time.time() - self.last_activity) > timeout_seconds
    
    def close(self):
        """Закрыть документ"""
        with self.lock:
            try:
                self.doc.close(True)
                if self.is_temp and self.file_path and os.path.exists(self.file_path):
                    os.remove(self.file_path)
                print(f"[Job {self.job_id}] Closed and cleaned up")
            except Exception as e:
                print(f"[Job {self.job_id}] Error closing: {e}")

class JobManager:
    """Менеджер заданий - управляет всеми активными сессиями"""
    
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()
        self.cleanup_thread = None
        self.running = True
        self._start_cleanup_thread()
    
    def _start_cleanup_thread(self):
        """Запустить поток для очистки просроченных заданий"""
        def cleanup_worker():
            while self.running:
                time.sleep(30)
                self._cleanup_expired_jobs()
        
        self.cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        self.cleanup_thread.start()
        print("[JobManager] Cleanup thread started")
    
    def _cleanup_expired_jobs(self):
        """Очистить просроченные задания"""
        with self.lock:
            expired = []
            for job_id, job in self.jobs.items():
                if job.is_expired(60):
                    expired.append(job_id)
            
            for job_id in expired:
                print(f"[JobManager] Cleaning expired job: {job_id}")
                job = self.jobs[job_id]
                job.close()
                del self.jobs[job_id]
    
    def create_job(self, template_path=None):
        """Создать новое задание с новым документом"""
        try:
            if template_path and template_path != "null" and template_path != "None":
                url = uno.systemPathToFileUrl(template_path)
                doc = uno_desktop.loadComponentFromURL(url, "_blank", 0, ())
                file_path = template_path
                is_temp = False
            else:
                doc = uno_desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
                file_path = None
                is_temp = True
            
            job_id = str(uuid.uuid4())
            job = Job(job_id, doc, file_path, is_temp)
            
            with self.lock:
                self.jobs[job_id] = job
            
            return job_id
        except Exception as e:
            print(f"[JobManager] Error creating job: {e}")
            return None
    
    def get_job(self, job_id):
        """Получить задание по ID"""
        with self.lock:
            job = self.jobs.get(job_id)
            if job:
                job.update_activity()
            return job
    
    def execute_macro(self, job_id, macro_code):
        """Выполнить макрос в контексте задания"""
        job = self.get_job(job_id)
        if not job:
            return f"ERROR: Job {job_id} not found or expired"
        
        with job.lock:
            try:
                safe_globals = {
                    "__builtins__": {
                        "print": print, "len": len, "str": str, "int": int,
                        "float": float, "bool": bool, "list": list, "dict": dict,
                        "range": range, "enumerate": enumerate, "zip": zip,
                        "isinstance": isinstance, "type": type, "tuple": tuple,
                        "set": set, "sum": sum, "min": min, "max": max,
                        "abs": abs, "round": round, "sorted": sorted,
                    },
                    "desktop": uno_desktop,
                    "doc": job.doc,
                    "uno": uno,
                    "PropertyValue": PropertyValue,
                    "XSCRIPTCONTEXT": type('obj', (object,), {'getDocument': lambda: job.doc})(),
                }
                
                exec(macro_code, safe_globals)
                return "SUCCESS: Macro executed"
            except Exception as e:
                return f"ERROR: {str(e)}\n{traceback.format_exc()}"
    
    def save_job(self, job_id, file_path):
        """Сохранить документ задания"""
        job = self.get_job(job_id)
        if not job:
            return f"ERROR: Job {job_id} not found or expired"
        
        with job.lock:
            try:
                url = uno.systemPathToFileUrl(file_path)
                job.doc.storeToURL(url, ())
                if job.is_temp and job.file_path:
                    job.is_temp = False
                return f"SUCCESS: Saved to {file_path}"
            except Exception as e:
                return f"ERROR: {str(e)}"
    
    def close_job(self, job_id, save_path=None):
        """Закрыть задание, опционально сохранив"""
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return f"ERROR: Job {job_id} not found"
            
            if save_path and save_path != "null" and save_path != "None":
                try:
                    url = uno.systemPathToFileUrl(save_path)
                    job.doc.storeToURL(url, ())
                except Exception as e:
                    print(f"[Job {job_id}] Error saving: {e}")
            
            job.close()
            del self.jobs[job_id]
            return f"SUCCESS: Job {job_id} closed"
    
    def get_active_jobs(self):
        """Получить список активных заданий"""
        with self.lock:
            return list(self.jobs.keys())
    
    def shutdown(self):
        """Завершить работу"""
        self.running = False
        with self.lock:
            for job_id, job in list(self.jobs.items()):
                job.close()
            self.jobs.clear()

# ==================== ПОДКЛЮЧЕНИЕ К LIBREOFFICE ====================

def init_libreoffice(port=2002):
    """Инициализация подключения к LibreOffice"""
    global uno_context, uno_desktop
    try:
        local_context = uno.getComponentContext()
        resolver = local_context.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local_context)
        uno_context = resolver.resolve(f"uno:socket,host=localhost,port={port};urp;StarOffice.ComponentContext")
        uno_desktop = uno_context.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", uno_context)
        print(f"Connected to LibreOffice on port {port}")
        return True
    except Exception as e:
        print(f"Error connecting to LibreOffice: {e}")
        return False

# ==================== ВСЕ ФУНКЦИИ ДЛЯ HTTP ОБРАБОТЧИКА ====================

def Ping():
    return "OK"

def CreateJob(template_path=None):
    global job_manager
    if job_manager is None:
        return json.dumps({"status": "ERROR", "message": "Job manager not initialized"})
    
    job_id = job_manager.create_job(template_path)
    if job_id:
        return json.dumps({"status": "SUCCESS", "job_id": job_id})
    else:
        return json.dumps({"status": "ERROR", "message": "Failed to create job"})

def ExecuteMacroInJob(job_id, macro_code):
    global job_manager
    if job_manager is None:
        return "ERROR: Job manager not initialized"
    return job_manager.execute_macro(job_id, macro_code)

def SaveJob(job_id, file_path):
    global job_manager
    if job_manager is None:
        return "ERROR: Job manager not initialized"
    return job_manager.save_job(job_id, file_path)

def CloseJob(job_id, save_path=None):
    global job_manager
    if job_manager is None:
        return "ERROR: Job manager not initialized"
    return job_manager.close_job(job_id, save_path)

def GetActiveJobs():
    global job_manager
    if job_manager is None:
        return json.dumps({"jobs": []})
    return json.dumps({"jobs": job_manager.get_active_jobs()})

def GetJobInfo(job_id):
    global job_manager
    if job_manager is None:
        return json.dumps({"error": "Job manager not initialized"})
    
    job = job_manager.get_job(job_id)
    if job:
        return json.dumps({
            "job_id": job.job_id,
            "file_path": job.file_path,
            "is_temp": job.is_temp,
            "created_at": job.created_at,
            "last_activity": job.last_activity,
            "is_expired": job.is_expired()
        })
    else:
        return json.dumps({"error": "Job not found"})

def CreateReportFromData(data_json, template_path=None, output_path=None, keep_open=True):
    """Создание отчёта из JSON данных
    keep_open: True - оставить документ открытым, False - закрыть после сохранения
    """
    try:
        data = json.loads(data_json)
        
        if template_path and template_path != "null" and template_path != "None":
            url = uno.systemPathToFileUrl(template_path)
            doc = uno_desktop.loadComponentFromURL(url, "_blank", 0, ())
        else:
            doc = uno_desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
        
        sheet = doc.getSheets().getByIndex(0)
        
        row_offset = data.get('row_offset', 0)
        col_offset = data.get('col_offset', 0)
        rows = data.get('rows', [])
        
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                cell = sheet.getCellByPosition(col_offset + j, row_offset + i)
                if isinstance(value, (int, float)):
                    cell.setValue(value)
                else:
                    cell.setString(str(value))
        
        if output_path and output_path != "null" and output_path != "None":
            url = uno.systemPathToFileUrl(output_path)
            doc.storeToURL(url, ())
            
            # Если НЕ нужно оставлять открытым - закрываем
            if not keep_open:
                doc.close(True)
                return f"SUCCESS: Report saved and closed to {output_path}"
            else:
                # Документ остаётся открытым
                return f"SUCCESS: Report saved and OPEN (document ready for editing) to {output_path}"
        else:
            # Без сохранения - закрываем если не нужно оставлять открытым
            if not keep_open:
                doc.close(True)
                return f"SUCCESS: Report created with {len(rows)} rows (closed)"
            else:
                return f"SUCCESS: Report created with {len(rows)} rows (OPEN)"
    except Exception as e:
        return f"ERROR: {str(e)}"

def ExecuteMacro(macro_code, output_path=None):
    if not uno_desktop:
        return "ERROR: LibreOffice not initialized"
    
    doc = None
    try:
        doc = uno_desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
        
        safe_globals = {
            "__builtins__": {
                "print": print, "len": len, "str": str, "int": int,
                "float": float, "bool": bool, "list": list, "dict": dict,
                "range": range, "enumerate": enumerate, "zip": zip,
                "isinstance": isinstance, "type": type,
            },
            "desktop": uno_desktop,
            "doc": doc,
            "uno": uno,
            "PropertyValue": PropertyValue,
        }
        
        exec(macro_code, safe_globals)
        
        if output_path and output_path != "null" and output_path != "None":
            url = uno.systemPathToFileUrl(output_path)
            doc.storeToURL(url, ())
        
        doc.close(True)
        return "SUCCESS: Macro executed"
    except Exception as e:
        if doc:
            try:
                doc.close(True)
            except:
                pass
        return f"ERROR: {str(e)}\n{traceback.format_exc()}"

def ExecuteMacroLegacy(macro_code, output_path=None):
    return ExecuteMacro(macro_code, output_path)

def ExportToPDF(doc_path, pdf_path):
    try:
        url = uno.systemPathToFileUrl(doc_path)
        doc = uno_desktop.loadComponentFromURL(url, "_blank", 0, ())
        
        filter_data = PropertyValue()
        filter_data.Name = "FilterName"
        filter_data.Value = "calc_pdf_Export"
        
        pdf_url = uno.systemPathToFileUrl(pdf_path)
        doc.storeToURL(pdf_url, (filter_data,))
        doc.close(True)
        return f"SUCCESS: PDF saved to {pdf_path}"
    except Exception as e:
        return f"ERROR: {str(e)}"

def ExportToPDFFromJob(job_id, pdf_path):
    global job_manager
    job = job_manager.get_job(job_id)
    if not job:
        return f"ERROR: Job {job_id} not found"
    
    with job.lock:
        try:
            filter_data = PropertyValue()
            filter_data.Name = "FilterName"
            filter_data.Value = "calc_pdf_Export"
            
            pdf_url = uno.systemPathToFileUrl(pdf_path)
            job.doc.storeToURL(pdf_url, (filter_data,))
            return f"SUCCESS: PDF saved to {pdf_path}"
        except Exception as e:
            return f"ERROR: {str(e)}"

def GetCellValue(sheet_name, col, row):
    try:
        doc = uno_desktop.getCurrentComponent()
        if not doc:
            return "ERROR: No active document"
        sheet = doc.getSheets().getByName(sheet_name)
        cell = sheet.getCellByPosition(col, row)
        try:
            value = cell.getValue()
            if value != 0:
                return str(value)
        except:
            pass
        return cell.getString()
    except Exception as e:
        return f"ERROR: {str(e)}"

def SetCellValue(sheet_name, col, row, value):
    try:
        doc = uno_desktop.getCurrentComponent()
        if not doc:
            return "ERROR: No active document"
        sheet = doc.getSheets().getByName(sheet_name)
        cell = sheet.getCellByPosition(col, row)
        if isinstance(value, (int, float)):
            cell.setValue(value)
        else:
            cell.setString(str(value))
        return "SUCCESS"
    except Exception as e:
        return f"ERROR: {str(e)}"

def CloseCurrentDocument():
    try:
        doc = uno_desktop.getCurrentComponent()
        if doc:
            doc.close(True)
            return "SUCCESS: Document closed"
        return "ERROR: No active document"
    except Exception as e:
        return f"ERROR: {str(e)}"

def GetOpenDocuments():
    try:
        docs = uno_desktop.getComponents()
        result = []
        for doc in docs:
            try:
                url = doc.getURL()
                if url:
                    result.append(url)
            except:
                pass
        return json.dumps({"documents": result})
    except Exception as e:
        return f"ERROR: {str(e)}"

def CreateSpreadsheet():
    try:
        doc = uno_desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
        url = doc.getURL()
        return json.dumps({"status": "SUCCESS", "url": url})
    except Exception as e:
        return f"ERROR: {str(e)}"

def OpenSpreadsheet(file_path):
    try:
        url = uno.systemPathToFileUrl(file_path)
        doc = uno_desktop.loadComponentFromURL(url, "_blank", 0, ())
        return json.dumps({"status": "SUCCESS", "url": doc.getURL()})
    except Exception as e:
        return f"ERROR: {str(e)}"

def SaveDocument(file_path):
    try:
        doc = uno_desktop.getCurrentComponent()
        if not doc:
            return "ERROR: No active document"
        url = uno.systemPathToFileUrl(file_path)
        doc.storeToURL(url, ())
        return f"SUCCESS: Saved to {file_path}"
    except Exception as e:
        return f"ERROR: {str(e)}"

def GetSheets():
    try:
        doc = uno_desktop.getCurrentComponent()
        if not doc:
            return json.dumps({"error": "No active document"})
        sheets = doc.getSheets()
        result = []
        for i in range(sheets.getCount()):
            result.append(sheets.getByIndex(i).getName())
        return json.dumps({"sheets": result})
    except Exception as e:
        return f"ERROR: {str(e)}"

def GetUsedRange(sheet_name):
    try:
        doc = uno_desktop.getCurrentComponent()
        if not doc:
            return json.dumps({"error": "No active document"})
        sheet = doc.getSheets().getByName(sheet_name)
        cursor = sheet.createCursor()
        cursor.gotoEndOfUsedArea(True)
        rows = cursor.getRows().getCount()
        cols = cursor.getColumns().getCount()
        return json.dumps({"rows": rows, "cols": cols})
    except Exception as e:
        return f"ERROR: {str(e)}"

def ApplyStyle(sheet_name, col, row, style_name):
    try:
        doc = uno_desktop.getCurrentComponent()
        if not doc:
            return "ERROR: No active document"
        sheet = doc.getSheets().getByName(sheet_name)
        cell = sheet.getCellByPosition(col, row)
        cell.setPropertyValue("CellStyle", style_name)
        return "SUCCESS"
    except Exception as e:
        return f"ERROR: {str(e)}"

def MergeCells(sheet_name, start_col, start_row, end_col, end_row):
    try:
        doc = uno_desktop.getCurrentComponent()
        if not doc:
            return "ERROR: No active document"
        sheet = doc.getSheets().getByName(sheet_name)
        range_address = sheet.getCellRangeByPosition(start_col, start_row, end_col, end_row).getRangeAddress()
        sheet.merge(range_address)
        return "SUCCESS"
    except Exception as e:
        return f"ERROR: {str(e)}"

def InsertRow(sheet_name, row_index):
    try:
        doc = uno_desktop.getCurrentComponent()
        if not doc:
            return "ERROR: No active document"
        sheet = doc.getSheets().getByName(sheet_name)
        rows = sheet.getRows()
        rows.insertByIndex(row_index, 1)
        return "SUCCESS"
    except Exception as e:
        return f"ERROR: {str(e)}"

def DeleteRow(sheet_name, row_index):
    try:
        doc = uno_desktop.getCurrentComponent()
        if not doc:
            return "ERROR: No active document"
        sheet = doc.getSheets().getByName(sheet_name)
        rows = sheet.getRows()
        rows.removeByIndex(row_index, 1)
        return "SUCCESS"
    except Exception as e:
        return f"ERROR: {str(e)}"

def SetColumnWidth(sheet_name, col_index, width):
    try:
        doc = uno_desktop.getCurrentComponent()
        if not doc:
            return "ERROR: No active document"
        sheet = doc.getSheets().getByName(sheet_name)
        columns = sheet.getColumns()
        column = columns.getByIndex(col_index)
        column.setPropertyValue("Width", width)
        return "SUCCESS"
    except Exception as e:
        return f"ERROR: {str(e)}"

def SetRowHeight(sheet_name, row_index, height):
    try:
        doc = uno_desktop.getCurrentComponent()
        if not doc:
            return "ERROR: No active document"
        sheet = doc.getSheets().getByName(sheet_name)
        rows = sheet.getRows()
        row = rows.getByIndex(row_index)
        row.setPropertyValue("Height", height)
        return "SUCCESS"
    except Exception as e:
        return f"ERROR: {str(e)}"

def AddChart(sheet_name, range_address, chart_name, width, height, x, y):
    try:
        doc = uno_desktop.getCurrentComponent()
        if not doc:
            return "ERROR: No active document"
        sheet = doc.getSheets().getByName(sheet_name)
        rect = uno.createUnoStruct("com.sun.star.awt.Rectangle")
        rect.Width = width
        rect.Height = height
        rect.X = x
        rect.Y = y
        
        range_addr = sheet.getCellRangeByName(range_address).getRangeAddress()
        charts = sheet.getCharts()
        charts.addNewByName(chart_name, rect, (range_addr,), True, True)
        return "SUCCESS"
    except Exception as e:
        return f"ERROR: {str(e)}"

# ==================== HTTP ОБРАБОТЧИК ====================

class SmartGridHandler(BaseHTTPRequestHandler):
    
    def do_GET(self):
        if self.path == "/ping":
            self._send_response(200, "text/plain", Ping())
        elif self.path == "/status":
            status = {
                "server": "running",
                "libreoffice": "connected" if uno_desktop else "disconnected",
                "port": 2002,
                "active_jobs": len(job_manager.get_active_jobs()) if job_manager else 0
            }
            self._send_response(200, "application/json", json.dumps(status))
        elif self.path == "/jobs":
            self._send_response(200, "application/json", GetActiveJobs())
        elif self.path.startswith("/job/"):
            parts = self.path.split('/')
            if len(parts) >= 3:
                job_id = parts[2]
                self._send_response(200, "application/json", GetJobInfo(job_id))
            else:
                self._send_response(400, "text/plain", "Bad request")
        elif self.path == "/documents":
            self._send_response(200, "application/json", GetOpenDocuments())
        elif self.path == "/sheets":
            self._send_response(200, "application/json", GetSheets())
        else:
            self._send_response(404, "text/plain", "Not Found")
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        
        if self.path == "/function":
            try:
                data = json.loads(post_data)
                func_name = data.get('function', '')
                args = data.get('args', [])

                safe_functions = {
                    "Ping": Ping,
                    "CreateJob": CreateJob,
                    "ExecuteMacroInJob": ExecuteMacroInJob,
                    "SaveJob": SaveJob,
                    "CloseJob": CloseJob,
                    "GetActiveJobs": GetActiveJobs,
                    "GetJobInfo": GetJobInfo,
                    "CreateReportFromData": CreateReportFromData,
                    "ExecuteMacro": ExecuteMacro,
                    "ExecuteMacroLegacy": ExecuteMacroLegacy,
                    "ExportToPDF": ExportToPDF,
                    "ExportToPDFFromJob": ExportToPDFFromJob,
                    "GetCellValue": GetCellValue,
                    "SetCellValue": SetCellValue,
                    "CloseCurrentDocument": CloseCurrentDocument,
                    "GetOpenDocuments": GetOpenDocuments,
                    "CreateSpreadsheet": CreateSpreadsheet,
                    "OpenSpreadsheet": OpenSpreadsheet,
                    "SaveDocument": SaveDocument,
                    "GetSheets": GetSheets,
                    "GetUsedRange": GetUsedRange,
                    "ApplyStyle": ApplyStyle,
                    "MergeCells": MergeCells,
                    "InsertRow": InsertRow,
                    "DeleteRow": DeleteRow,
                    "SetColumnWidth": SetColumnWidth,
                    "SetRowHeight": SetRowHeight,
                    "AddChart": AddChart,
                }
                
                if func_name in safe_functions:
                    result = safe_functions[func_name](*args)
                else:
                    result = f"Function '{func_name}' not found"
                
                self._send_response(200, "text/plain", str(result))
            except Exception as e:
                self._send_response(400, "text/plain", f"Error: {e}")
        
        elif self.path == "/execute":
            try:
                data = json.loads(post_data)
                code = data.get('code', '')
                safe_globals = {
                    "desktop": uno_desktop, 
                    "uno": uno,
                    "PropertyValue": PropertyValue
                }
                exec(code, safe_globals)
                self._send_response(200, "text/plain", "SUCCESS")
            except Exception as e:
                self._send_response(400, "text/plain", f"ERROR: {e}")
        
        elif self.path == "/execute_with_result":
            try:
                data = json.loads(post_data)
                code = data.get('code', '')
                local_dict = {}
                exec(code, {"desktop": uno_desktop, "uno": uno}, local_dict)
                result = local_dict.get('result', 'No result variable')
                self._send_response(200, "text/plain", str(result))
            except Exception as e:
                self._send_response(400, "text/plain", f"ERROR: {e}")
        
        elif self.path == "/batch":
            try:
                data = json.loads(post_data)
                commands = data.get('commands', [])
                results = []
                for cmd in commands:
                    func_name = cmd.get('function', '')
                    args = cmd.get('args', [])
                    if func_name in safe_functions:
                        results.append(safe_functions[func_name](*args))
                    else:
                        results.append(f"Function '{func_name}' not found")
                self._send_response(200, "application/json", json.dumps({"results": results}))
            except Exception as e:
                self._send_response(400, "text/plain", f"ERROR: {e}")
        
        else:
            self._send_response(404, "text/plain", "Not Found")
    
    def _send_response(self, code, content_type, data):
        self.send_response(code)
        self.send_header('Content-type', f'{content_type}; charset=utf-8')
        self.end_headers()
        self.wfile.write(str(data).encode('utf-8'))
    
    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")

# ==================== ЗАПУСК СЕРВЕРА ====================

def run_server(port=8080, lo_port=2002):
    global job_manager
    
    print("=" * 80)
    print("SmartGrid Web Server v4.0 - FULL VERSION with ALL FUNCTIONS")
    print("=" * 80)
    
    if init_libreoffice(lo_port):
        print(f"✓ Connected to LibreOffice on port {lo_port}")
    else:
        print(f"✗ WARNING: Could not connect to LibreOffice on port {lo_port}")
    
    job_manager = JobManager()
    
    server_address = ('localhost', port)
    httpd = HTTPServer(server_address, SmartGridHandler)
    
    print("=" * 80)
    print(f"✓ Server running at http://localhost:{port}")
    print("")
    print("ENDPOINTS:")
    print("  GET  /ping                    - Check server status")
    print("  GET  /status                  - Full server status")
    print("  GET  /jobs                    - List active jobs")
    print("  GET  /job/{job_id}            - Job information")
    print("  GET  /documents               - List open documents")
    print("  GET  /sheets                  - List sheets in current document")
    print("  POST /function                - Call any function")
    print("  POST /execute                 - Execute raw Python code")
    print("  POST /execute_with_result     - Execute code and return result")
    print("  POST /batch                   - Batch execute multiple functions")
    print("")
    print("AVAILABLE FUNCTIONS (32 functions):")
    print("  • Job Management: Ping, CreateJob, ExecuteMacroInJob, SaveJob,")
    print("    CloseJob, GetActiveJobs, GetJobInfo, ExportToPDFFromJob")
    print("  • Document: CreateSpreadsheet, OpenSpreadsheet, SaveDocument,")
    print("    CloseCurrentDocument, GetOpenDocuments, ExportToPDF")
    print("  • Cell/Sheet: GetCellValue, SetCellValue, GetSheets, GetUsedRange")
    print("  • Formatting: ApplyStyle, MergeCells, SetColumnWidth, SetRowHeight")
    print("  • Structure: InsertRow, DeleteRow")
    print("  • Charts: AddChart")
    print("  • Macros: ExecuteMacro, ExecuteMacroLegacy, CreateReportFromData")
    print("  • Batch: Execute multiple commands in one request")
    print("")
    print("JOB MANAGER FEATURES:")
    print("  • Each job has unique ID for session isolation")
    print("  • Jobs auto-expire after 60 seconds of inactivity")
    print("  • Multiple clients can work simultaneously")
    print("  • One client can manage multiple jobs")
    print("=" * 80)
    print("Press Ctrl+C to stop")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹ Shutting down...")
        if job_manager:
            job_manager.shutdown()
        print("✓ Server stopped")
        httpd.server_close()

if __name__ == '__main__':
    port = 8080
    lo_port = 2002
    
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    if len(sys.argv) > 2:
        lo_port = int(sys.argv[2])
    
    run_server(port, lo_port)
