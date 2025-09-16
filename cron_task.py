# cron_task.pyw
# Финальная версия: "Планировщик задач" — всё работает, чисто, стабильно

import subprocess
import time
import logging
import threading
import json
import os
from datetime import datetime
from croniter import croniter
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import shlex
import chardet  # pip install chardet
from PIL import Image, ImageTk  # pip install pillow

# --- Путь к файлу задач ---
TASKS_FILE = "cron_task.json"

# --- Список задач: (cron_expr, full_command) ---
TASKS = []

# --- Глобальные переменные ---
log_messages = []
scheduled_jobs = []  # [{cron_iter, next_run, task, expr}, ...]
stop_event = threading.Event()

# --- GUI переменные ---
root = None
log_text = None
minute_var = None
hour_var = None
day_var = None
month_var = None
weekday_var = None
command_entry = None
tasks_frame = None
sort_reset_btn = None

# --- Состояние сортировки ---
sort_key = None  # 'cron', 'command', 'next_run'
sort_reverse = False
original_tasks_order = []  # Актуальный сохранённый порядок

# --- Хранение виджетов ---
task_widgets = []  # [cron_lbl, cmd_lbl, next_lbl, btn_frame]

# --- Для динамического логирования ---
LOG_DIR = "log"
os.makedirs(LOG_DIR, exist_ok=True)  # Создаём папку log
current_log_file = None
logger = None

# --- Для синхронизации лога ---
log_lock = threading.Lock()

# --- Кэширование для оптимизации ---
last_log_hash = None


def get_today_log_file():
    """Вернуть путь к файлу лога на сегодня"""
    today = datetime.now().strftime('%Y-%m-%d')
    return os.path.join(LOG_DIR, f"cron_task_{today}.log")


def setup_logger():
    """Настроить логгер с учётом текущей даты"""
    global logger, current_log_file

    new_log_file = get_today_log_file()

    if new_log_file != current_log_file:
        current_log_file = new_log_file

        if logger and logger.hasHandlers():
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)
                handler.close()

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(current_log_file, encoding='utf-8', mode='a'),
                logging.StreamHandler()
            ]
        )
        logger = logging.getLogger()


def log_message(msg):
    """Записать сообщение в лог (файл и GUI)"""
    setup_logger()
    logging.info(msg)
    log_messages.append(msg)


def load_tasks():
    """Загрузить задачи из JSON-файла"""
    global TASKS, original_tasks_order
    if not os.path.exists(TASKS_FILE):
        TASKS = []
        save_tasks()
        log_message("📌 Создан новый файл задач: cron_task.json")
    else:
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    TASKS = []
                    for item in data:
                        if isinstance(item, list) and len(item) == 2:
                            cron_expr, full_cmd = item
                            TASKS.append((cron_expr, full_cmd))
                        else:
                            log_message(f"⚠️ Пропущена некорректная запись: {item}")
                    log_message(f"📌 Загружено {len(TASKS)} задач из {TASKS_FILE}")
                else:
                    TASKS = []
                    log_message("⚠️ Неверный формат файла. Ожидается список.")
                    save_tasks()
        except Exception as e:
            TASKS = []
            log_message(f"❌ Ошибка чтения {TASKS_FILE}: {e}")
            save_tasks()

    # ✅ original_tasks_order = актуальный порядок при загрузке
    original_tasks_order[:] = TASKS.copy()


def save_tasks():
    """Сохранить задачи в JSON-файл"""
    try:
        data_to_save = [[cron, cmd] for cron, cmd in TASKS]
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        log_message(f"Задачи сохранены в {TASKS_FILE}")
    except Exception as e:
        log_message(f"❌ Не удалось сохранить задачи: {e}")


def detect_and_decode(data_bytes) -> str:
    """Автоматически определить кодировку и декодировать"""
    if not data_bytes:
        return ""

    try:
        return data_bytes.decode('utf-8')
    except UnicodeDecodeError:
        pass

    detected = chardet.detect(data_bytes)
    encoding = detected.get('encoding', 'utf-8')

    try:
        return data_bytes.decode(encoding)
    except:
        for enc in ['cp1251', 'cp866']:
            try:
                return data_bytes.decode(enc)
            except:
                continue
        return data_bytes.decode('utf-8', errors='replace')


def run_script(full_command_str):
    """Выполнение команды с ID задачи и атомарной записью в лог"""
    start_time = time.time()
    timestamp = datetime.now().strftime("%H:%M:%S")

    task_id_str = ""
    for i, (cron, cmd) in enumerate(TASKS):
        if cmd == full_command_str:
            task_id_str = f"[#{i}] "
            break
    if not task_id_str:
        task_id_str = "[#?]"  # Неизвестный ID

    task_header = f"{task_id_str}[{timestamp}] Задача: {full_command_str}"

    # Буфер вывода
    output_lines = []

    def buffer_log(msg):
        output_lines.append(msg)

    buffer_log(f"🔄 {task_header}")
    buffer_log(f"┌───────────────────────────────")

    try:
        try:
            args = shlex.split(full_command_str)
        except ValueError as e:
            buffer_log(f"❌ Ошибка разбора команды: {e}")
            return

        if not args:
            buffer_log("❌ Пустая команда")
            return

        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

        # Чтение stdout
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                decoded_line = detect_and_decode(line).strip()
                if decoded_line:
                    out_time = datetime.now().strftime("%H:%M:%S")
                    buffer_log(f"│ 📤 [{out_time}] {decoded_line}")

        # Чтение stderr
        stderr_raw = process.stderr.read()
        if stderr_raw:
            stderr_lines = stderr_raw.splitlines()
            for line in stderr_lines:
                decoded_line = detect_and_decode(line).strip()
                if decoded_line:
                    err_time = datetime.now().strftime("%H:%M:%S")
                    buffer_log(f"│ ❌ [{err_time}] {decoded_line}")

        return_code = process.returncode
        end_time = datetime.now().strftime("%H:%M:%S")
        duration = time.time() - start_time

        if return_code == 0:
            buffer_log(f"│ ✅ [{end_time}] Успешно завершена")
        else:
            buffer_log(f"│ 💥 [{end_time}] Ошибка (код {return_code})")

        buffer_log(f"│ ⏱️ [{end_time}] Время выполнения: {duration:.3f} сек")

    except Exception as e:
        exc_time = datetime.now().strftime("%H:%M:%S")
        buffer_log(f"│ 💀 [{exc_time}] Исключение: {e}")
    finally:
        buffer_log(f"└───────────────────────────────")

        # 🔐 Атомарная запись в лог
        with log_lock:
            for line in output_lines:
                log_message(line)
            root.after(0, update_gui)


def setup_schedules():
    """Настроить все cron-задачи — без лишних логов при сортировке"""
    global scheduled_jobs
    scheduled_jobs.clear()
    base_time = datetime.now()

    for cron_expr, full_command in TASKS:
        try:
            if not croniter.is_valid(cron_expr):
                continue

            cron_iter = croniter(cron_expr, base_time)
            next_run = cron_iter.get_next(datetime)

            scheduled_jobs.append({
                "cron_iter": cron_iter,
                "next_run": next_run,
                "task": full_command,
                "expr": cron_expr
            })
        except Exception as e:
            pass  # Молча пропускаем (или раскомментировать для отладки)
            # log_message(f"⚠️ Ошибка парсинга cron '{cron_expr}': {e}")


def check_schedules():
    """Проверка расписания"""
    now = datetime.now()
    for job in scheduled_jobs[:]:
        if now >= job["next_run"]:
            full_command = job["task"]
            threading.Thread(target=run_script, args=(full_command,), daemon=True).start()

            try:
                job["next_run"] = job["cron_iter"].get_next(datetime)
            except Exception as e:
                log_message(f"⚠️ Ошибка пересчёта cron: {e}")
                scheduled_jobs.remove(job)


def update_gui():
    """Обновить интерфейс: умное обновление лога, стабильная прокрутка"""
    global task_widgets, sort_key, sort_reverse, sort_reset_btn, last_log_hash

    tasks_frame.columnconfigure(0, weight=0)
    tasks_frame.columnconfigure(1, weight=1)
    tasks_frame.columnconfigure(2, weight=0)
    tasks_frame.columnconfigure(3, weight=0)

    job_map = {job["expr"]: job["next_run"] for job in scheduled_jobs}

    display_data = []
    for i, (cron, cmd) in enumerate(TASKS):
        next_run = job_map.get(cron, None)
        next_str = next_run.strftime("%H:%M %d.%m") if next_run else "—"
        display_data.append({
            "index": i,
            "cron": cron,
            "command": cmd,
            "next_run": next_run,
            "next_str": next_str
        })

    if sort_key:
        if sort_key == "next_run":
            display_data.sort(
                key=lambda x: x["next_run"] or datetime.max,
                reverse=sort_reverse
            )
        else:
            display_data.sort(
                key=lambda x: x[sort_key],
                reverse=sort_reverse
            )

    for i, data in enumerate(display_data):
        row = i + 3
        bg = "#f0f0f0" if i % 2 == 0 else "white"

        if i < len(task_widgets):
            cron_lbl, cmd_lbl, next_lbl, btn_frame = task_widgets[i]
            cron_lbl.config(text=data["cron"], bg=bg)
            cmd_lbl.config(text=data["command"], bg=bg)
            next_lbl.config(text=data["next_str"], bg=bg)
            btn_frame.config(bg=bg)
        else:
            cron_lbl = tk.Label(tasks_frame, text=data["cron"], width=15, anchor="w", font=("Courier", 9), height=1, bg=bg)
            cron_lbl.grid(row=row, column=0, padx=5, pady=1, sticky="w")

            cmd_lbl = tk.Label(tasks_frame, text=data["command"], anchor="w", font=("Courier", 9), fg="blue", height=1, bg=bg)
            cmd_lbl.grid(row=row, column=1, padx=5, pady=1, sticky="ew")

            next_lbl = tk.Label(tasks_frame, text=data["next_str"], width=18, anchor="w", font=("Courier", 9), height=1, bg=bg)
            next_lbl.grid(row=row, column=2, padx=5, pady=1, sticky="w")

            btn_frame = tk.Frame(tasks_frame, bg=bg)
            btn_frame.grid(row=row, column=3, padx=5, pady=1, sticky="e")

            # --- Кнопки с иконками ---
            copy_btn = tk.Button(
                btn_frame, text="➕", width=3, height=1,
                command=lambda idx=data["index"]: copy_task_by_index(idx),
                bg="lightgreen", font=("Arial", 9)
            )
            copy_btn.pack(side=tk.LEFT, padx=1)
            Tooltip(copy_btn, "Копировать задачу")

            delete_btn = tk.Button(
                btn_frame, text="➖", width=3, height=1,
                command=lambda idx=data["index"]: delete_task_by_index(idx),
                bg="red", fg="white", font=("Arial", 9)
            )
            delete_btn.pack(side=tk.LEFT, padx=1)
            Tooltip(delete_btn, "Удалить задачу")

            task_widgets.append([cron_lbl, cmd_lbl, next_lbl, btn_frame])

    while len(task_widgets) > len(display_data):
        widgets = task_widgets.pop()
        for w in widgets:
            w.grid_forget()
            w.destroy()

    # --- Умное обновление лога ---
    current_log_hash = hash(tuple(log_messages[-500:]))

    if current_log_hash != last_log_hash:
        log_text.config(state='normal')

        prev_view = log_text.yview()
        was_at_bottom = prev_view[1] >= 0.99
        current_pos = prev_view[0]

        log_text.delete(1.0, tk.END)
        for msg in log_messages[-500:]:
            log_text.insert(tk.END, msg + "\n")

        if was_at_bottom:
            log_text.see(tk.END)
        else:
            log_text.yview_moveto(current_pos)

        log_text.config(state='disabled')

        last_log_hash = current_log_hash

    if sort_reset_btn:
        sort_reset_btn.config(state='normal' if sort_key else 'disabled')


def browse_file():
    """Выбрать скрипт, сохранив аргументы"""
    path = filedialog.askopenfilename(
        title="Выберите скрипт",
        filetypes=[
            ("Python", "*.py"),
            ("Bash", "*.sh"),
            ("Batch", "*.bat"),
            ("Исполняемые", "*.exe"),
            ("Все файлы", "*.*")
        ]
    )
    if not path:
        return

    current = command_entry.get().strip()
    if not current:
        command_entry.insert(0, path)
        return

    try:
        parts = shlex.split(current)
    except:
        parts = current.split()

    if not parts:
        command_entry.delete(0, tk.END)
        command_entry.insert(0, path)
        return

    args = ' '.join([shlex.quote(arg) for arg in parts[1:]]) if len(parts) > 1 else ''
    new_cmd = f"{path} {args}".strip()

    command_entry.delete(0, tk.END)
    command_entry.insert(0, new_cmd)


def add_task():
    """Добавить задачу с проверкой на дубли"""
    try:
        m = minute_var.get().strip()
        h = hour_var.get().strip()
        dom = day_var.get().strip()
        mon = month_var.get().strip()
        dow = weekday_var.get().strip()

        cron_expr = f"{m} {h} {dom} {mon} {dow}"

        if not croniter.is_valid(cron_expr):
            messagebox.showerror("Ошибка", f"Неверное cron-выражение: {cron_expr}")
            return

        full_command = command_entry.get().strip()
        if not full_command:
            messagebox.showwarning("Предупреждение", "Введите команду")
            return

        for existing_cron, existing_cmd in TASKS:
            if existing_cron == cron_expr and existing_cmd == full_command:
                messagebox.showwarning(
                    "Дубликат",
                    "Такая задача уже существует:\n"
                    f"Время: {cron_expr}\n"
                    f"Команда: {full_command}"
                )
                return

        TASKS.append((cron_expr, full_command))

        # ✅ Сохраняем и синхронизируем эталон
        save_tasks()
        original_tasks_order[:] = TASKS.copy()

        setup_schedules()
        # ✅ Логируем задачи один раз при добавлении
        log_message(f"📌 Добавлена задача: {cron_expr} → {full_command}")
        root.after(0, update_gui)

        messagebox.showinfo("Готово", "Задача добавлена и сохранена")
        command_entry.delete(0, tk.END)

    except Exception as e:
        messagebox.showerror("Ошибка", f"Не удалось добавить задачу: {e}")


def copy_task_by_index(index):
    """Копировать задачу по индексу в TASKS"""
    if index < 0 or index >= len(TASKS):
        return

    cron_expr, full_command = TASKS[index]
    parts = cron_expr.split()
    if len(parts) == 5:
        m, h, dom, mon, dow = parts
        minute_var.set(m)
        hour_var.set(h)
        day_var.set(dom)
        month_var.set(mon)
        weekday_var.set(dow)

    command_entry.delete(0, tk.END)
    command_entry.insert(0, full_command)


def delete_task_by_index(index):
    """Удалить задачу по индексу в TASKS"""
    if index < 0 or index >= len(TASKS):
        return

    cron_expr, full_command = TASKS[index]
    if not messagebox.askyesno("Подтверждение", f"Удалить задачу?\n{cron_expr}\n→ {full_command}"):
        return

    del TASKS[index]

    # ✅ Сохраняем и синхронизируем эталон
    save_tasks()
    original_tasks_order[:] = TASKS.copy()

    setup_schedules()
    root.after(0, update_gui)
    log_message(f"🗑️ Удалена задача: {cron_expr} → {full_command}")


def sort_by(key):
    """Сортировка по ключу — изменяет порядок в TASKS только в памяти"""
    global sort_key, sort_reverse
    if sort_key == key:
        sort_reverse = not sort_reverse
    else:
        sort_key = key
        sort_reverse = False

    job_map = {job["expr"]: job["next_run"] for job in scheduled_jobs}

    temp_data = []
    for cron, cmd in TASKS:
        next_run = job_map.get(cron, None)
        temp_data.append({
            "cron": cron,
            "command": cmd,
            "next_run": next_run
        })

    if sort_key == "next_run":
        temp_data.sort(key=lambda x: x["next_run"] or datetime.max, reverse=sort_reverse)
    else:
        temp_data.sort(key=lambda x: x[sort_key], reverse=sort_reverse)

    TASKS[:] = [(item["cron"], item["command"]) for item in temp_data]
    setup_schedules()
    root.after(0, update_gui)


def reset_sort():
    """Сбросить сортировку — вернуть последний сохранённый порядок"""
    global sort_key, sort_reverse
    sort_key = None
    sort_reverse = False

    TASKS[:] = original_tasks_order.copy()
    setup_schedules()
    root.after(0, update_gui)


def create_headers():
    """Создать заголовки с сортировкой"""
    tk.Label(tasks_frame, text="Cron", width=15, anchor="w", font=("Courier", 9, "bold"), bg="lightgray").grid(
        row=0, column=0, padx=5, pady=1, sticky="w")
    tk.Label(tasks_frame, text="Команда", anchor="w", font=("Courier", 9, "bold"), bg="lightgray").grid(
        row=0, column=1, padx=5, pady=1, sticky="ew")
    tk.Label(tasks_frame, text="Ближайшее выполнение", width=18, anchor="w", font=("Courier", 9, "bold"), bg="lightgray").grid(
        row=0, column=2, padx=5, pady=1, sticky="w")
    tk.Label(tasks_frame, text="Действия", anchor="e", font=("Courier", 9, "bold"), bg="lightgray").grid(
        row=0, column=3, padx=5, pady=1, sticky="e")

    tasks_frame.grid_slaves(row=0, column=0)[0].bind("<Button-1>", lambda e: sort_by("cron"))
    tasks_frame.grid_slaves(row=0, column=1)[0].bind("<Button-1>", lambda e: sort_by("command"))
    tasks_frame.grid_slaves(row=0, column=2)[0].bind("<Button-1>", lambda e: sort_by("next_run"))


def clear_form():
    """Очистить форму — вернуть значения по умолчанию"""
    minute_var.set("0")
    hour_var.set("9")
    day_var.set("*")
    month_var.set("*")
    weekday_var.set("*")
    command_entry.delete(0, tk.END)


class Tooltip:
    """Простая подсказка при наведении"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip = None
        self.widget.bind("<Enter>", self.show)
        self.widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25

        self.tooltip = tk.Toplevel(self.widget)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")

        label = tk.Label(
            self.tooltip,
            text=self.text,
            background="#ffffe0",
            relief="solid",
            borderwidth=1,
            font=("Arial", 9),
            padx=5,
            pady=3
        )
        label.pack()

    def hide(self, event=None):
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None


def bind_shortcuts(entry):
    """Привязать горячие клавиши — работают при любой раскладке (EN/RU)"""
    undo_stack = []
    redo_stack = []
    MAX_HISTORY = 50

    def save_state():
        current = entry.get()
        if not undo_stack or undo_stack[-1] != current:
            undo_stack.append(current)
            if len(undo_stack) > MAX_HISTORY:
                undo_stack.pop(0)
        redo_stack.clear()

    def undo(event):
        if len(undo_stack) > 1:
            current = entry.get()
            redo_stack.append(current)
            prev_state = undo_stack[-2]
            entry.delete(0, tk.END)
            entry.insert(0, prev_state)
            entry.icursor(tk.END)
            undo_stack.pop()
        return "break"

    def redo(event):
        if redo_stack:
            state = redo_stack.pop()
            undo_stack.append(state)
            entry.delete(0, tk.END)
            entry.insert(0, state)
            entry.icursor(tk.END)
        return "break"

    def copy(event):
        try:
            root.clipboard_clear()
            root.clipboard_append(entry.selection_get())
        except tk.TclError:
            pass
        return "break"

    def cut(event):
        copy(event)
        try:
            entry.delete("sel.first", "sel.last")
            save_state()
        except tk.TclError:
            pass
        return "break"

    def paste(event):
        try:
            text = root.clipboard_get()
            entry.insert(tk.INSERT, text)
            save_state()
        except tk.TclError:
            pass
        return "break"

    def select_all(event):
        entry.select_range(0, tk.END)
        entry.icursor(tk.END)
        return "break"

    save_state()

    def on_key_release(event):
        if event.keysym in ('Control_L', 'Control_R'):
            return
        save_state()

    entry.bind("<KeyRelease>", on_key_release)
    entry.bind("<FocusOut>", lambda e: on_key_release(e))

    # --- Универсальный обработчик для Ctrl + любая клавиша ---
    def on_control_key(event):
        if event.state & 0x4:  # Проверяем, что нажат Ctrl
            key = event.keysym.lower()
            char = event.char.lower() if event.char else ''

            key_to_check = key if len(key) == 1 else char

            if key_to_check in ('a', 'ф'):
                return select_all(event)
            elif key_to_check in ('c', 'с'):
                return copy(event)
            elif key_to_check in ('x', 'ы'):
                return cut(event)
            elif key_to_check in ('v', 'м'):
                return paste(event)
            elif key_to_check in ('z', 'я'):
                return undo(event)
            elif key_to_check in ('y', 'ч'):
                return redo(event)

    entry.bind("<Control-KeyPress>", on_control_key)

    # Стандартные англоязычные комбинации
    entry.bind("<Control-a>", select_all)
    entry.bind("<Control-A>", select_all)
    entry.bind("<Control-c>", copy)
    entry.bind("<Control-C>", copy)
    entry.bind("<Control-x>", cut)
    entry.bind("<Control-X>", cut)
    entry.bind("<Control-v>", paste)
    entry.bind("<Control-V>", paste)
    entry.bind("<Control-z>", undo)
    entry.bind("<Control-Z>", undo)
    entry.bind("<Control-y>", redo)
    entry.bind("<Control-Y>", redo)

    entry.bind("<Button-1>", lambda e: entry.focus())


def main():
    global root, log_text, sort_reset_btn
    global minute_var, hour_var, day_var, month_var, weekday_var, command_entry, tasks_frame

    setup_logger()
    load_tasks()

    root = tk.Tk()

    # --- Установка иконки из папки img ---
    icon_path = "img/app_icon.ico"
    if os.path.exists(icon_path):
        try:
            root.iconbitmap(icon_path)
        except Exception as e:
            print(f"⚠️ Не удалось загрузить иконку: {e}")

    root.title("Планировщик задач")
    root.geometry("1280x750")
    root.minsize(800, 400)  # ✅ Минимальная ширина 800px

    def on_closing():
        stop_event.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)

    # Переменные
    minute_var = tk.StringVar(value="0")
    hour_var = tk.StringVar(value="9")
    day_var = tk.StringVar(value="*")
    month_var = tk.StringVar(value="*")
    weekday_var = tk.StringVar(value="*")

    # --- Основной контейнер формы ---
    form_container = tk.Frame(root)
    form_container.pack(padx=20, pady=10, fill="x")

    # --- Левая часть: логотип (90x90), без рамки ---
    logo_frame = tk.Frame(form_container, width=90, height=90, relief="sunken")
    logo_frame.pack_propagate(False)
    logo_frame.pack(side=tk.LEFT, padx=(0, 10))

    logo_label = tk.Label(logo_frame)
    logo_label.place(relx=0.5, rely=0.5, anchor="center")

    # Загрузка логотипа
    logo_path = "img/logo.png"
    if os.path.exists(logo_path):
        try:
            image = Image.open(logo_path)
            image = image.resize((90, 90), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            logo_label.config(image=photo)
            logo_label.image = photo
        except Exception as e:
            print(f"⚠️ Не удалось загрузить логотип: {e}")
            logo_label.config(text="Логотип\nне загружен", justify="center", fg="gray", font=("Arial", 7))
    else:
        logo_label.config(text="Логотип\nне найден", justify="center", fg="gray", font=("Arial", 7))

    # --- Правая часть: форма добавления задачи ---
    input_frame = tk.LabelFrame(form_container, text="Добавить задачу", padx=10, pady=10)
    input_frame.pack(side=tk.LEFT, fill="x", expand=True)

    for i in range(18):
        input_frame.columnconfigure(i, weight=1 if i < 11 else 0)

    tk.Label(input_frame, text="Мин", font=("Arial", 8, "bold")).grid(row=0, column=0, padx=2, pady=(0, 2), sticky="n")
    tk.Label(input_frame, text="Час", font=("Arial", 8, "bold")).grid(row=0, column=1, padx=2, pady=(0, 2), sticky="n")
    tk.Label(input_frame, text="День мес", font=("Arial", 8, "bold")).grid(row=0, column=2, padx=2, pady=(0, 2), sticky="n")
    tk.Label(input_frame, text="Месяц", font=("Arial", 8, "bold")).grid(row=0, column=3, padx=2, pady=(0, 2), sticky="n")
    tk.Label(input_frame, text="День нед", font=("Arial", 8, "bold")).grid(row=0, column=4, padx=2, pady=(0, 2), sticky="n")
    tk.Label(input_frame, text="Команда", font=("Arial", 8, "bold")).grid(row=0, column=5, columnspan=10, padx=2, pady=(0, 2), sticky="n")

    tk.Entry(input_frame, textvariable=minute_var, width=6).grid(row=1, column=0, padx=2, pady=2)
    tk.Entry(input_frame, textvariable=hour_var, width=6).grid(row=1, column=1, padx=2, pady=2)
    tk.Entry(input_frame, textvariable=day_var, width=6).grid(row=1, column=2, padx=2, pady=2)
    tk.Entry(input_frame, textvariable=month_var, width=6).grid(row=1, column=3, padx=2, pady=2)
    tk.Entry(input_frame, textvariable=weekday_var, width=6).grid(row=1, column=4, padx=2, pady=2)

    global command_entry
    command_entry = tk.Entry(input_frame, font=("Courier", 10))
    command_entry.grid(row=1, column=5, columnspan=10, padx=2, pady=2, sticky="ew")

    bind_shortcuts(command_entry)

    tk.Button(input_frame, text="📁", width=3, command=browse_file).grid(row=1, column=15, padx=2, pady=2, sticky="e")
    tk.Button(input_frame, text="➕", width=3, command=add_task, bg="lightgreen").grid(row=1, column=16, padx=2, pady=2, sticky="e")

    # --- Кнопка "Очистить" с иконкой и подсказкой ---
    clear_btn = tk.Button(
        input_frame,
        text="➖",
        width=3,
        height=1,
        command=clear_form,
        bg="red",
        fg="white",
        font=("Arial", 10, "bold")
    )
    clear_btn.grid(row=1, column=17, padx=2, pady=2, sticky="e")
    Tooltip(clear_btn, "Очистить форму")

    # --- Основной контейнер ---
    main_container = tk.Frame(root)
    main_container.pack(padx=20, pady=(0, 5), fill="both", expand=True)

    tk.Label(main_container, text="Список задач", font=("Arial", 11, "bold")).pack(pady=(0, 2), anchor="w")

    sort_control_frame = tk.Frame(main_container)
    sort_control_frame.pack(pady=(0, 5), anchor="w")
    sort_reset_btn = tk.Button(
        sort_control_frame,
        text="🔄 Сброс сортировки",
        command=reset_sort,
        state='disabled'
    )
    sort_reset_btn.pack(side=tk.LEFT)

    global tasks_frame
    tasks_frame = tk.Frame(main_container)
    tasks_frame.pack(fill="both", expand=True)

    create_headers()
    ttk.Separator(tasks_frame, orient="horizontal").grid(row=1, column=0, columnspan=4, sticky="ew", pady=1)

    tk.Label(main_container, text="Лог выполнения", font=("Arial", 11, "bold")).pack(pady=(5, 2), anchor="w")
    global log_text
    log_text = scrolledtext.ScrolledText(
        main_container,
        wrap=tk.WORD,
        height=12,
        font=("Courier", 9),
        state='disabled',
        padx=10,
        pady=10,
        bg="#f9f9f9"
    )
    log_text.pack(fill="both", expand=True)

    # --- Статус-бар ---
    status_frame = tk.Frame(root, height=25)
    status_frame.pack(side="bottom", fill="x")
    status_frame.pack_propagate(False)

    status = tk.Label(
        status_frame,
        text="🟢 Работает",
        bd=1,
        relief=tk.SUNKEN,
        anchor=tk.W,
        fg="green",
        font=("Arial", 9),
        bg="#f0f0f0"
    )
    status.pack(fill="x", expand=True)

    # --- Фоновый поток ---
    def scheduler_worker():
        setup_schedules()
        while not stop_event.is_set():
            check_schedules()
            time.sleep(1)
            try:
                root.after(0, update_gui)
            except:
                break

    thread = threading.Thread(target=scheduler_worker, daemon=True)
    thread.start()

    # ✅ Логируем задачи один раз при старте
    for cron, cmd in TASKS:
        log_message(f"📌 Задача запланирована: {cron} → {cmd}")

    update_gui()
    root.mainloop()


if __name__ == "__main__":
    main()