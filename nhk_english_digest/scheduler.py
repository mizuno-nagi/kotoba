import time
import logging

import schedule
import yaml

from logging_setup import configure_logging
from main import BASE_DIR, CONFIG_PATH, ensure_config, run_refresh_job


configure_logging(BASE_DIR)


def scheduled_job():
    print("[Scheduler] 触发每日全局刷新")
    try:
        run_refresh_job()
    except SystemExit as exc:
        print(f"[Scheduler] 每日刷新未运行：{exc}")
    except Exception as exc:
        print(f"[Scheduler] 每日刷新失败：{exc}")


def main():
    config = ensure_config(CONFIG_PATH)
    schedule_time = config.get("schedule_time", "07:00")
    schedule.every().day.at(schedule_time).do(scheduled_job)
    print(f"[Scheduler] 已启动，每天 {schedule_time} 执行")
    print("[Scheduler] 按 Ctrl+C 停止")

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[Scheduler] 已停止")
