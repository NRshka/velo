from collections import namedtuple
from contextlib import closing
from typing import List, Dict

from sqlalchemy import update
from sqlalchemy import bindparam

from project.models import DataItems, VersionItems, Category, TmpTable, Version, Diff

version_item = namedtuple("VersionItem", "id,version,path,label,class_id")


def get_items_of_version(sess, version_id: List[int]) -> List[version_item]:
    """Если в старшем версии датасета изменен класс, возвращется только последняя запись"""
    deleted_items = Diff \
        .query \
        .filter(Diff.version_id.in_(version_id)) \
        .with_entities(Diff.item_id) \
        .all()
    query = sess.query(VersionItems, DataItems, Category) \
        .filter(VersionItems.version_id.in_(version_id)) \
        .join(DataItems) \
        .filter(Category.id == VersionItems.category_id) \
        .filter(DataItems.id.notin_(deleted_items)) \
        .order_by(DataItems.id, VersionItems.version_id.desc()) \
        .distinct(DataItems.id)
    return [version_item(item.DataItems.id,
                         item.VersionItems.version_id,
                         item.DataItems.path,
                         item.Category.name,
                         item.Category.id
                         ) for item in query.all()]


def get_id_by_name(node_name: str) -> int:
    id = Version \
        .query \
        .filter(Version.name == node_name) \
        .with_entities(Version.id) \
        .first()
    return id.id


def get_uncommited_items(sess, node_name: str) -> List[version_item]:
    node_id = get_id_by_name(node_name)
    query = sess.query(TmpTable, DataItems, Category) \
        .filter(TmpTable.node_name == node_name) \
        .join(DataItems) \
        .filter(Category.id == TmpTable.category_id)
    return [version_item(item.DataItems.id,
                         node_id,
                         item.DataItems.path,
                         item.Category.name,
                         item.Category.id,
                         ) for item in query.all()]


def uncommited_items_filter(sess, item_ids) -> List[int]:
    """Возвращает id только незакомиченных объектов"""
    query = sess.query(TmpTable) \
        .filter(TmpTable.item_id.in_(item_ids))
    return [item.item_id for item in query.all()]


def update_uncommited_items(db, uncommited: Dict) -> None:
    stmt = (
        update(TmpTable).
            where(TmpTable.item_id == bindparam('id')).
            values(category_id=bindparam('new_category'))
    )
    update_values = []
    for item_id, moderation in uncommited.items():
        upd_item = dict(
            id=item_id,
            new_category=int(moderation['cl'])
        )
        update_values.append(upd_item)
    with db.engine.begin() as conn:
        conn.execute(
            stmt,
            update_values
        )
    return


if __name__ == '__main__':
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("postgresql://velo:123@localhost:5432/velo")
    Session = sessionmaker(bind=engine)
    session = Session()
    with closing(session) as sess:
        res = get_items_of_version(sess, [2])
        # res = get_items_of_version(session, [1, 2])
        for item in res:
            print(f"Item id: {item.id}")
            print(f"Item path: {item.path}")
            print(f"Version id: {item.version}")
            print(f"Label: {item.label}")
