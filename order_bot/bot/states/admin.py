from aiogram.fsm.state import State, StatesGroup


class AddPractical(StatesGroup):
    subject = State()
    title = State()
    description = State()
    price = State()
    confirm = State()


class EditPractical(StatesGroup):
    title = State()
    description = State()
    price = State()


class SettingsEdit(StatesGroup):
    help_text = State()


class AdminComment(StatesGroup):
    text = State()          # адмін пише коментар до замовлення


class Delivery(StatesGroup):
    files = State()         # адмін надсилає виконану роботу клієнту
