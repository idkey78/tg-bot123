"""Витяг та повторне надсилання файлів із повідомлень Telegram."""
from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import Message

from bot.utils.formatting import esc


@dataclass(frozen=True, slots=True)
class FileInfo:
    file_type: str
    file_id: str
    file_name: str | None
    caption: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "file_type": self.file_type,
            "file_id": self.file_id,
            "file_name": self.file_name,
            "caption": self.caption,
        }


def extract_file(message: Message) -> FileInfo | None:
    """Повертає інформацію про файл у повідомленні або None, якщо файлу немає."""
    caption = (message.caption or "").strip()[:500] or None
    if message.document:
        return FileInfo("document", message.document.file_id, message.document.file_name, caption)
    if message.photo:
        return FileInfo("photo", message.photo[-1].file_id, "Фото", caption)
    if message.video:
        return FileInfo("video", message.video.file_id, message.video.file_name or "Відео", caption)
    if message.audio:
        return FileInfo("audio", message.audio.file_id, message.audio.file_name or "Аудіо", caption)
    if message.voice:
        return FileInfo("voice", message.voice.file_id, "Голосове", caption)
    if message.video_note:
        return FileInfo("video_note", message.video_note.file_id, "Відеоповідомлення", None)
    return None


async def send_stored_file(
    bot: Bot, chat_id: int, file_type: str, file_id: str, caption: str | None = None
) -> None:
    """Надсилає збережений файл за file_id (caption — вже безпечний HTML)."""
    if file_type == "photo":
        await bot.send_photo(chat_id, file_id, caption=caption)
    elif file_type == "video":
        await bot.send_video(chat_id, file_id, caption=caption)
    elif file_type == "audio":
        await bot.send_audio(chat_id, file_id, caption=caption)
    elif file_type == "voice":
        await bot.send_voice(chat_id, file_id, caption=caption)
    elif file_type == "video_note":
        await bot.send_video_note(chat_id, file_id)
    else:
        await bot.send_document(chat_id, file_id, caption=caption)


def file_title(name: str | None, file_type: str) -> str:
    return esc(name) if name else esc(file_type)
