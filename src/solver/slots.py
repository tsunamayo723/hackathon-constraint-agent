"""
スロット（時間のコマ）ユーティリティ

ソルバーは「時間」を連続値ではなく、営業時間を slot_minutes 単位で刻んだ
**スロット（コマ）の集合**として扱う。
例: 11:00〜14:00 を30分刻み → 11:00-11:30, 11:30-12:00, ... の6コマ。

ここでは時刻計算（HH:MM ⇔ 分）と、スロット展開だけを担当する。
制約の翻訳（どのスロットに人を置くか）はハンドラ側の仕事。
"""

from datetime import date, timedelta


def hhmm_to_min(hhmm: str) -> int:
    """ "HH:MM" を「0時からの経過分」に変換する。例: "11:30" → 690 """
    hh, mm = hhmm.split(":")
    return int(hh) * 60 + int(mm)


def min_to_hhmm(total_min: int) -> str:
    """ 「0時からの経過分」を "HH:MM" に変換する。例: 690 → "11:30" """
    hh = total_min // 60
    mm = total_min % 60
    return f"{hh:02d}:{mm:02d}"


def date_range(start: date, end: date) -> list[date]:
    """ start〜end（両端を含む）の日付リストを返す """
    days = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days


class Slot:
    """1日の中の1コマ。index は同一日内での通し番号。"""

    def __init__(self, index: int, start_min: int, end_min: int):
        self.index = index
        self.start_min = start_min
        self.end_min = end_min

    @property
    def start(self) -> str:
        return min_to_hhmm(self.start_min)

    @property
    def end(self) -> str:
        return min_to_hhmm(self.end_min)

    def is_within(self, window_start_min: int, window_end_min: int) -> bool:
        """このコマが [window_start, window_end) に完全に収まるか"""
        return self.start_min >= window_start_min and self.end_min <= window_end_min

    def __repr__(self) -> str:
        return f"Slot({self.start}-{self.end})"


def build_day_slots(open_hhmm: str, close_hhmm: str, slot_minutes: int) -> list[Slot]:
    """
    営業時間を slot_minutes 単位のコマに分割する（1日分）。

    例: open="10:00", close="12:00", slot_minutes=30
        → [10:00-10:30, 10:30-11:00, 11:00-11:30, 11:30-12:00]
    """
    open_min = hhmm_to_min(open_hhmm)
    close_min = hhmm_to_min(close_hhmm)

    slots: list[Slot] = []
    cur = open_min
    idx = 0
    while cur + slot_minutes <= close_min:
        slots.append(Slot(idx, cur, cur + slot_minutes))
        cur += slot_minutes
        idx += 1
    return slots
