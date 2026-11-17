"""Константи: предмети, статуси, ліміти, тексти за замовчуванням."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Subject:
    key: str
    title: str
    emoji: str

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.title}"


SUBJECTS: dict[str, Subject] = {
    "info": Subject("info", "Обробка інформації", "📚"),
    "ce": Subject("ce", "Комп'ютерна інженерія", "💻"),
}


def subject_title(key: str) -> str:
    subject = SUBJECTS.get(key)
    return subject.title if subject else key


def subject_label(key: str) -> str:
    subject = SUBJECTS.get(key)
    return subject.label if subject else key


# --- Статуси замовлень ---
STATUS_NEW = "new"
STATUS_ACCEPTED = "accepted"
STATUS_IN_PROGRESS = "in_progress"
STATUS_AWAITING_PAYMENT = "awaiting_payment"
STATUS_DONE = "done"
STATUS_REJECTED = "rejected"

STATUS_LABELS: dict[str, str] = {
    STATUS_NEW: "🆕 Нове",
    STATUS_ACCEPTED: "🟡 Прийняте",
    STATUS_IN_PROGRESS: "🔵 У роботі",
    STATUS_AWAITING_PAYMENT: "💰 Очікує особистої оплати",
    STATUS_DONE: "✅ Виконане",
    STATUS_REJECTED: "❌ Відхилене",
}
STATUS_EMOJI: dict[str, str] = {k: v.split(" ", 1)[0] for k, v in STATUS_LABELS.items()}
STATUS_ORDER: tuple[str, ...] = tuple(STATUS_LABELS)

# --- Типи оплати ---
PAYMENT_REGULAR = "regular"
PAYMENT_CUSTOM = "custom"

# --- Файли замовлень ---
FILE_KIND_TASK = "task"      # файли із завданням від клієнта
FILE_KIND_RESULT = "result"  # виконана робота від адміністратора
MAX_TASK_FILES = 10

CUSTOM_PRACTICAL_TITLE = "Custom-практична"

# --- Обмеження введення ---
TITLE_MAX = 100
DESCRIPTION_MAX = 1000
CUSTOM_OFFER_MAX = 200
STUDENT_INFO_MAX = 150
COMMENT_MAX = 1000
PRICE_MAX = 1_000_000
HELP_TEXT_MAX = 1500

PAGE_SIZE = 6

# --- Налаштування (таблиця settings) ---
SETTING_ORDERS_ENABLED = "orders_enabled"
SETTING_HELP_TEXT = "help_text"

DEFAULT_HELP_TEXT = (
    "<b>Як оформити замовлення</b>\n"
    "1. Оберіть предмет у головному меню.\n"
    "2. Оберіть практичну роботу та натисніть «Замовити» — або оберіть "
    "«Custom-практична» і надішліть файл із власним завданням.\n"
    "3. Оберіть звичайну оплату або запропонуйте власну суму.\n"
    "4. Вкажіть ім'я, прізвище та групу (можна пропустити).\n"
    "5. Перевірте дані та підтвердіть замовлення.\n\n"
    "Після оформлення ви можете залишати коментарі до замовлення та уточнювати "
    "деталі — виконавець отримає їх у Telegram. Виконану роботу бот надішле вам "
    "у цей чат.\n\n"
    "Оплата здійснюється особисто, онлайн-платежів у боті немає."
)
