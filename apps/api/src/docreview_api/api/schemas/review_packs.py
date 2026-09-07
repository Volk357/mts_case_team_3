"""Public transport schemas for the Review Packs catalog."""

from typing import Literal

from pydantic import Field

from docreview_api.api.schemas.common import ApiModel, OpaqueId


class ReviewPackContentResponse(ApiModel):
    """Один файл настройки пакета: что он задаёт и лежит ли он в пакете."""

    key: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    description: str = Field(min_length=1)
    present: bool


class ReviewPackResponse(ApiModel):
    """Public metadata for one server-approved Review Pack version."""

    review_pack_id: OpaqueId
    display_name: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    version: str = Field(min_length=1)
    # Состав пакета — чем он перенастраивается под другую компанию.
    # Пустой список допустим: у пакета может не быть манифеста.
    contents: list[ReviewPackContentResponse] = Field(default_factory=list)
    # Склонность приёмки: по ней человек выбирает профиль. `null` — пакет
    # её не объявляет, интерфейс тогда ничего не подписывает.
    policy_bias: Literal["recall", "precision", "balanced"] | None = None


class ReviewPackListResponse(ApiModel):
    """Stable envelope for the tenant-visible Review Pack catalog."""

    items: list[ReviewPackResponse]
    total: int = Field(ge=0)


class ReviewPackSourceResponse(ApiModel):
    """Тексты настраиваемых файлов пакета — то, что открывается в редакторе.

    Отдаются только файлы, которые ядро действительно применяет: показать
    здесь файл, который ядро проигнорирует, значило бы дать править то,
    что ни на что не влияет.
    """

    review_pack_id: OpaqueId
    pack_key: str = Field(min_length=1)
    version: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    files: dict[str, str]


class ReviewPackVersionRequest(ApiModel):
    """Запрос на выпуск новой версии пакета.

    Версия обязательна и не выводится автоматически: человек должен
    осознанно назвать то, на что будут ссылаться результаты проверок.
    Опубликованная версия неизменяема, поэтому правка всегда порождает
    новую, а не переписывает существующую.
    """

    version: str = Field(min_length=1, max_length=50)
    files: dict[str, str] = Field(min_length=1)


class ReviewPackVersionResponse(ApiModel):
    review_pack_id: OpaqueId
    pack_key: str = Field(min_length=1)
    version: str = Field(min_length=1)
