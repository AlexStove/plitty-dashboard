# -*- coding: utf-8 -*-
"""
code_interpreter.py - Интерактивный Code Interpreter & Python Sandbox для Plitty.
Позволяет безопасно выполнять произвольный Python-код, производить сложные вычисления,
обрабатывать данные и строить графики (matplotlib) на лету.
"""

import sys
import os
import io
import time
import json
import traceback
import subprocess
import tempfile

# Фикс кодировки
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CHARTS_DIR = os.path.join(os.path.dirname(__file__), "web_dashboard", "screens")
os.makedirs(CHARTS_DIR, exist_ok=True)

def execute_code(code_str, timeout_seconds=20):
    """
    Выполняет Python-код в изолированном процессе и возвращает результат,
    вывод в stdout, ошибки и ссылки на сгенерированные графики.
    """
    chart_filename = f"chart_{int(time.time()*1000)}.png"
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    chart_rel_url = f"/screens/{chart_filename}"
    
    # Шаблон-обертка для перехвата графиков matplotlib
    wrapper_code = f"""# -*- coding: utf-8 -*-
import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Перехват matplotlib для автоматического сохранения графиков
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    _orig_show = plt.show
    def _custom_show(*args, **kwargs):
        plt.savefig(r"{chart_path}", bbox_inches='tight', dpi=120)
        plt.close()
    plt.show = _custom_show
except ImportError:
    pass

# Пользовательский код
try:
{chr(10).join('    ' + line for line in code_str.splitlines())}
except Exception as _e:
    print(f"[Execution Error] {{_e}}", file=sys.stderr)
    traceback.print_exc()
"""

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(wrapper_code)
        temp_script = f.name

    start_time = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, temp_script],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace"
        )
        duration = round(time.time() - start_time, 3)
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        
        has_chart = os.path.exists(chart_path) and os.path.getsize(chart_path) > 100
        
        return {
            "success": proc.returncode == 0 and not stderr,
            "stdout": stdout,
            "stderr": stderr,
            "duration_sec": duration,
            "has_chart": has_chart,
            "chart_path": chart_path if has_chart else None,
            "chart_url": chart_rel_url if has_chart else None
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Превышен лимит времени выполнения ({timeout_seconds} сек)",
            "duration_sec": timeout_seconds,
            "has_chart": False,
            "chart_path": None,
            "chart_url": None
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "duration_sec": round(time.time() - start_time, 3),
            "has_chart": False,
            "chart_path": None,
            "chart_url": None
        }
    finally:
        if os.path.exists(temp_script):
            try:
                os.remove(temp_script)
            except Exception:
                pass
