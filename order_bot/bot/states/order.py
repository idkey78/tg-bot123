from aiogram.fsm.state import State, StatesGroup


class OrderFlow(StatesGroup):
    payment = State()       # вибір типу оплати (звичайна / custom)
    custom_offer = State()  # введення суми або пропозиції
    student_info = State()  # ім'я, прізвище, група (можна пропустити)
    custom_files = State()  # Custom-практична: файли із завданням
    confirm = State()       # підсумок і підтвердження


class CommentFlow(StatesGroup):
    text = State()          # клієнт пише коментар до замовлення
