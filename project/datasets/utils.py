import asyncio
import enum
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator, Dict, List, Optional, Union
from multiprocessing import Process
import multiprocessing
from project.todo.rabbitmq_connector import send_message, get_message
from flask import flash
from project import db
from project.models import Version, Category, DataItems, TmpTable

from project.video_utils import ffmpeg_job

log = logging.getLogger(__name__)

# TODO: вынести процессы и очереди куда нибудь
sending_queue = multiprocessing.Queue()
sending_process = Process(
    target=send_message,
    args=('frames_extraction', sending_queue),
    daemon=True
)
sending_process.start()

# pulling_queue = multiprocessing.Queue()
# print("Объявление ", id(pulling_queue))
# pulling_process = Process(
#     target=get_message,
#     args=('frames_extraction_result', pulling_queue),
#     daemon=True
# )
# pulling_process.start()


image_extensions = ['.jpg', '.png', '.bmp']
audio_extensions = ['.mp3', '.wav']

# TODO: в конфиг
OUT_DIR = Path("./project/static/images/tmp")
if not OUT_DIR.exists():
    OUT_DIR.mkdir()


class MediaType(str, enum.Enum):
    VIDEO = "VIDEO"
    TEXT = "TEXT"
    PHOTO = "PHOTO"
    AUDIO = "AUDIO"

    @classmethod
    def has_value(cls, value):
        return value in cls._value2member_map_


@dataclass
class DataSample:
    path: str
    category: Union[str, int]
    media_type: MediaType


def get_media_type(file: Path) -> MediaType:
    if file.suffix in image_extensions:
        return MediaType.PHOTO
    elif file.suffix in audio_extensions:
        return MediaType.AUDIO
    return MediaType.VIDEO


def add_cv_catregory(version_name: str, category_name: str) -> int:
    version = Version.query.filter_by(name=version_name).first()

    if not version:
        raise RuntimeError(f"Can't add category to unexisted version {version_name}")

    category = Category(name=category_name, version_id=version.id, task=1)
    db.session.add(category)
    db.session.flush()

    db.session.commit()

    return category.id


def import_data(categories: List[str], objects: List[DataItems], selected: str, version: Version) -> None:
    try:
        db.session.bulk_save_objects(objects, return_defaults=True)
        tmp = [TmpTable(item_id=obj.id,
                        node_name=selected,
                        category_id=cat) for obj, cat in zip(objects, categories)]
        db.session.bulk_save_objects(tmp)
    except Exception as ex:
        log.error(ex)
        db.session.rollback()
    else:
        # change status to STAGE which means that version is not empty
        version.status = 2
        db.session.commit()
    return


def fillup_tmp_table(
    label_ids: Dict[str, int],
    selected: str,
    src: str,
    version: Version,
    commit_batch: int = 1000,
    create_missing_categories: bool = False,
    version_name: Optional[str] = None
) -> None:
    """
    Заполнить временную таблицу
    функция проходит по указанной директории src, добавляет найденные файлы в таблицу DataItems,
    заполняет таблицу TmpTable
    """
    objects, categories = [], []
    for sample in get_data_samples(
        src,
        label_ids,
        force_creating_categories=create_missing_categories,
        version_name=version_name
    ):
        res = DataItems.query.filter_by(path=sample.path).first()
        if res:
            continue
        data_item = DataItems(path=sample.path)
        objects.append(data_item)
        categories.append(sample.category)
        if len(objects) == commit_batch:
            import_data(categories, objects, selected, version)
            objects.clear()
            categories.clear()
    if len(objects):
        import_data(categories, objects, selected, version)
        objects.clear()
        categories.clear()


def get_data_samples(
    data_path_str: str,
    labels: Dict[str, int],
    force_creating_categories: bool = False,
    version_name: Optional[str] = None
) -> Generator[DataSample, None, None]:
    data_path: Path = Path(data_path_str)
    # # если это один файл
    if data_path.is_file():
        pass
    # ToDO добавить обработку, если указанная директория без подпапок
    #  (просто хранит файлы заданной категории)
    if data_path.is_dir():
        for item in data_path.iterdir():
            if item.is_dir():
                label = item.name
                if label not in labels:
                    log.warning(f"Folder name {label} not in labels of current version")

                    if force_creating_categories:
                        assert version_name, ValueError("version_name can't be None or '' if set flag force_creating_categories")

                    new_category_id = add_cv_catregory(version_name, label)
                    labels[label] = new_category_id
                for file in item.iterdir():
                    if file.is_file():
                        media_type = get_media_type(file)
                        sample = DataSample(str(file), labels[label], media_type)
                        yield sample
